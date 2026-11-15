"""建索引 + Chunk Size A/B。

- 切块：langchain RecursiveCharacterTextSplitter
- 向量库：langchain_community FAISS

用法：
    python -m app.rag.indexer build --docs data/knowledge.jsonl --chunk 200
    python -m app.rag.indexer build_dir --dir data/docs --chunk 200
    python -m app.rag.indexer abtest --docs data/knowledge.jsonl --chunks 100 200 500
"""
from __future__ import annotations

import argparse
import json
import logging
import os

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.parsers import SUPPORTED_EXTENSIONS, parse_file

# 网络上流传的题库 PDF 常有损坏的交叉引用表，pypdf 会为此刷出海量
# "Ignoring wrong pointing object ..." 警告，淹没真正的进度输出。
# 这些警告无害（pypdf 会跳过坏对象继续解析），降到 ERROR 级别即可。
logging.getLogger("pypdf").setLevel(logging.ERROR)


def _splitter(chunk_size: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )


CHECKPOINT_EVERY = 5       # 每 N 批存一次盘
MAX_BATCH_ATTEMPTS = 8     # 单批最多尝试次数
PROGRESS_FILE = ".build_progress.json"
# 每批片段数。实测 500 一批时，Ollama 的 embed 请求体会大到偶发失败
# （单请求约 20 万字符），且一批失败就损失 500 片进度。
# 降到 100：请求更小更稳、失败损失更少、内存峰值更低，代价是进度行更密。
BATCH_SIZE = 100


def _wait_for_ollama(timeout: float = 120.0, interval: float = 3.0) -> bool:
    """等待 Ollama 恢复可用。

    为什么需要：embed 失败的典型形态是 Ollama 内部 runner（llama-server）
    被替换或崩溃后短暂不可达。此时**立刻重试只会继续失败**——
    必须等主进程把模型重新加载好。实测连续失败 5 次的批次，
    加入健康探测等待后能正常恢复。
    """
    import time as _t

    from app.config import get_settings
    import httpx

    base = get_settings().ollama_base_url.rstrip("/")
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        try:
            r = httpx.get(f"{base}/api/tags", timeout=5.0)
            if r.status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        _t.sleep(interval)
    return False


def _fingerprint(documents: list[Document], chunk_size: int, model: str) -> str:
    """文档集合的指纹：用于判断断点文件是否对应当前这批内容。

    只要分块大小、嵌入模型、或任何片段内容变了，指纹就变，断点自动失效，
    避免"续跑到了与当前语料不匹配的半成品索引上"这种隐蔽错误。
    """
    import hashlib

    h = hashlib.sha256()
    h.update(f"{chunk_size}|{model}|{len(documents)}".encode("utf-8"))
    for d in documents:
        h.update(d.page_content.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _chunk_and_index(texts: list[tuple[str, str, str]], chunk_size: int, batch_size: int = BATCH_SIZE) -> int:
    """texts: (content, doc_id, source)。切块 → 分批向量化 → 建 FAISS → 落盘 documents.jsonl。

    工程要点（都是被真实故障逼出来的）：

    1. **分批**：数万片段一次性 `FAISS.from_documents` 会长时间无输出、内存峰值高、
       失败后无法定位。
    2. **单批重试 + 退避**：构建 1.4 万片段约 20 分钟，期间 Ollama 可能重载模型
       并分配新的内部端口，导致连接被拒。一次瞬时故障不该让整轮作废。
    3. **断点续跑**：每 5 批存一次索引与进度；中途失败后重跑会从断点继续，
       而不是从头再来。
    4. **失败即刷新 embedder 客户端**：陈旧连接是上面那类故障的根源，
       重建客户端比反复重试同一个坏连接有效。
    """
    from langchain_community.vectorstores import FAISS
    from app.rag.embeddings import get_embedder
    from app.config import get_settings

    import time as _time

    splitter = _splitter(chunk_size)
    documents: list[Document] = []
    for content, doc_id, source in texts:
        for i, ch in enumerate(splitter.split_text(content or "")):
            documents.append(Document(
                page_content=ch,
                metadata={"doc_id": f"{doc_id}#{i}", "source": source},
            ))

    if not documents:
        return 0

    index_dir = get_settings().faiss_index_dir
    os.makedirs(index_dir, exist_ok=True)
    progress_path = os.path.join(index_dir, PROGRESS_FILE)
    docs_path = os.path.join(index_dir, "documents.jsonl")

    s = get_settings()
    fp = _fingerprint(documents, chunk_size, s.embedding_model)
    total = len(documents)
    print(f"  共 {total} 个片段待向量化（每批 {batch_size}）")
    print(f"  语料指纹 {fp}")

    # ── 尝试断点续跑 ──
    vectorstore = None
    start_at = 0
    if os.path.exists(progress_path) and os.path.exists(os.path.join(index_dir, "index.faiss")):
        try:
            prog = json.load(open(progress_path, encoding="utf-8"))
            if prog.get("fingerprint") == fp and int(prog.get("total", -1)) == total:
                vectorstore = FAISS.load_local(
                    index_dir, get_embedder(), allow_dangerous_deserialization=True
                )
                start_at = int(prog.get("done", 0))
                print(f"  >>> 检测到未完成的构建：已完成 {start_at}/{total}，从断点继续")
            else:
                print("  断点文件与当前语料不匹配，将从头构建")
        except Exception as exc:  # noqa: BLE001
            print(f"  断点不可用（{type(exc).__name__}: {exc}），将从头构建")
            vectorstore, start_at = None, 0

    embedder = get_embedder()
    t0 = _time.perf_counter()
    base_done = start_at
    batch_no = 0

    for start in range(start_at, total, batch_size):
        batch = documents[start:start + batch_size]
        batch_no += 1

        # ── 单批重试 ──
        last_exc = None
        for attempt in range(MAX_BATCH_ATTEMPTS):
            try:
                if vectorstore is None:
                    vectorstore = FAISS.from_documents(batch, embedder)
                else:
                    vectorstore.add_documents(batch)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == MAX_BATCH_ATTEMPTS - 1:
                    break
                # 打印**完整错误信息**而非仅异常类型：只看类型无法定位
                # 是端口被拒、超时还是模型报错，白白浪费一轮排查
                detail = str(exc).replace("\n", " ")[:160]
                print(f"  !! 第 {batch_no} 批失败 [{type(exc).__name__}] {detail}",
                      flush=True)

                # 先等 Ollama 恢复健康再重试；盲目重试同一个坏连接没有意义
                healthy = _wait_for_ollama(timeout=60)
                if not healthy:
                    wait = min(60, 5 * (2 ** attempt))
                    print(f"     Ollama 未恢复，{wait}s 后再试（{attempt + 2}/{MAX_BATCH_ATTEMPTS}）",
                          flush=True)
                    _time.sleep(wait)

                # 刷新客户端：陈旧连接（模型重载换了内部端口）是这类失败的常见原因
                try:
                    get_embedder.cache_clear()
                except Exception:  # noqa: BLE001
                    pass
                embedder = get_embedder()
                if vectorstore is not None:
                    try:
                        vectorstore.embedding_function = embedder
                    except Exception:  # noqa: BLE001
                        pass

        if last_exc is not None:
            # 重试用尽：保留断点，让下次重跑能接着来
            _save_checkpoint(vectorstore, index_dir, progress_path, documents,
                             fp, total, min(start, total), chunk_size)
            print(f"\n  构建中断：第 {batch_no} 批连续 {MAX_BATCH_ATTEMPTS} 次失败。")
            print(f"  已完成 {start}/{total} 已保存，重新运行本脚本将从断点继续。")
            raise last_exc

        done = min(start + batch_size, total)
        elapsed = _time.perf_counter() - t0
        processed = done - base_done
        speed = processed / elapsed if elapsed else 0
        eta = (total - done) / speed if speed else 0
        print(f"  [{done}/{total}] {elapsed:.0f}s 已用, 约 {speed:.1f} 片段/s, "
              f"预计剩余 {eta / 60:.1f} 分钟", flush=True)

        # ── 定期落盘（断点）──
        if batch_no % CHECKPOINT_EVERY == 0 and done < total:
            _save_checkpoint(vectorstore, index_dir, progress_path, documents,
                             fp, total, done, chunk_size)
            print(f"      （已保存断点 {done}/{total}）", flush=True)

    # ── 全部完成：正式落盘并清除断点 ──
    vectorstore.save_local(index_dir)
    with open(docs_path, "w", encoding="utf-8") as f:
        for d in documents:
            f.write(json.dumps({"content": d.page_content, "metadata": d.metadata},
                               ensure_ascii=False) + "\n")
    try:
        os.remove(progress_path)
    except OSError:
        pass
    return len(documents)


def _save_checkpoint(vectorstore, index_dir, progress_path, documents,
                     fp, total, done, chunk_size) -> None:
    """保存半成品索引 + 进度标记。

    同时写 documents.jsonl：检索器要靠它重建 BM25 稀疏索引，
    只存 FAISS 而不存文档会导致"续跑出来的索引查不到内容"。
    """
    if vectorstore is None:
        return
    try:
        vectorstore.save_local(index_dir)
        docs_path = os.path.join(index_dir, "documents.jsonl")
        # 只写已进入索引的那部分：documents.jsonl 与 FAISS 必须一一对应，
        # 否则检索器重建的 BM25 稀疏索引会和稠密索引对不上。
        with open(docs_path, "w", encoding="utf-8") as f:
            for d in documents[:done]:
                f.write(json.dumps({"content": d.page_content, "metadata": d.metadata},
                                   ensure_ascii=False) + "\n")
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump({
                "fingerprint": fp,
                "total": total,
                "done": done,
                "chunk_size": chunk_size,
                "saved_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        print(f"      （断点保存失败：{type(exc).__name__}: {exc}，不影响继续构建）")


def build_index(docs_file: str, chunk_size: int) -> int:
    """从 JSONL 文件建索引（每行 {doc_id, content, source}）。"""
    with open(docs_file, encoding="utf-8") as f:
        raw = [json.loads(line) for line in f if line.strip()]
    texts = [(rd.get("content", ""), rd.get("doc_id", "doc"), rd.get("source", "")) for rd in raw]
    return _chunk_and_index(texts, chunk_size)


def build_index_from_dir(dir_path: str, chunk_size: int) -> int:
    """从目录建索引，自动解析 txt/md/docx/pdf。"""
    texts: list[tuple[str, str, str]] = []
    for name in sorted(os.listdir(dir_path)):
        path = os.path.join(dir_path, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        try:
            content = parse_file(path)
        except Exception as e:  # noqa: BLE001
            print(f"跳过 {name}：解析失败 {e}")
            continue
        if content and content.strip():
            texts.append((content, name, path))
    if not texts:
        print(f"目录 {dir_path} 下没有可解析的文件（支持 {sorted(SUPPORTED_EXTENSIONS)}）")
        return 0
    return _chunk_and_index(texts, chunk_size)


def _iter_files(dir_path: str, recursive: bool = True):
    """遍历目录下可解析的文件；recursive=True 时递归子目录。

    改造原因：原 `build_index_from_dir` 用 `os.listdir` 只扫一层，
    而真实资料（如「国企招聘笔试面试资料题库」）是**多层嵌套**结构，
    非递归会漏掉 90% 以上的文件。
    """
    root = os.path.abspath(dir_path)
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                yield os.path.join(dirpath, name)
    else:
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                yield p


def _collect_dir_texts(
    dir_path: str,
    recursive: bool = True,
    skip_prefixes: tuple[str, ...] = (),
) -> list[tuple[str, str, str]]:
    """把一个目录（可递归）解析成 (content, doc_id, source) 列表。

    doc_id 用**相对路径**（去掉扩展名）生成，保证：
      * 不同子目录下的同名文件不会互相覆盖；
      * doc_id 可读，便于在评测集里写 ground_truth_docs。
    """
    out: list[tuple[str, str, str]] = []
    root = os.path.abspath(dir_path)
    scanned = 0
    empty = 0
    failed = 0
    for path in _iter_files(dir_path, recursive=recursive):
        rel = os.path.relpath(path, root)
        # 跳过临时文件 / 系统文件（Word/PDF 打开时会生成 ~$xxx）
        if os.path.basename(path).startswith(("~$", ".")):
            continue
        if any(rel.startswith(p) for p in skip_prefixes):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        scanned += 1
        # 解析阶段原本完全静默（469 个文件要 5 分钟），这里给出行级进度
        if scanned == 1 or scanned % 50 == 0:
            print(f"    解析中 {scanned} 个文件...（已提取 {len(out)} 篇，"
                  f"空 {empty}，失败 {failed}）", flush=True)

        try:
            content = parse_file(path)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"    跳过 {rel}：解析失败 {type(e).__name__}: {e}")
            continue
        if content and content.strip():
            out.append((content, os.path.splitext(rel)[0], path))
        else:
            # 扫描件 PDF / 加密 PDF 提取为空，属正常损耗，计数而非报错
            empty += 1

    print(f"    解析完成：扫描 {scanned} 个，有效 {len(out)} 个，"
          f"空内容 {empty} 个（扫描件/加密），失败 {failed} 个")
    return out


def _resolve_chunk_size(cli_value: int | None) -> int:
    """分块大小的取值顺序：命令行 > .env 的 RAG_CHUNK_SIZE > 代码默认。

    修复：原来 CLI 把默认值硬编码成 200，导致 .env 里改 RAG_CHUNK_SIZE
    **完全不生效**（改了以为生效、实际索引没变）。这类"配置看起来能改、
    实际是死的"是最容易浪费排查时间的问题。
    """
    if cli_value:
        return cli_value
    try:
        from app.config import get_settings

        return int(get_settings().rag_chunk_size)
    except Exception:  # noqa: BLE001
        return 200


def build_all(
    docs_file: str,
    dir_path: str | None,
    chunk_size: int,
    extra_dirs: list[str] | None = None,
    recursive: bool = True,
) -> int:
    """合并「JSONL 知识库」与「文档目录（可含外部资料目录）」，建一份完整索引。

    为什么需要这个入口：原索引只从 `data/docs/` 建（2 个文件），
    而知识库主体 `data/knowledge.jsonl`（16 篇）从未进入索引。
    结果是 `search_knowledge` 只能召回 2 个片段，recall@k / MRR 恒为 0，
    RAG 相关指标完全失去意义 —— 这是评测不可信的一个根因。

    `extra_dirs` 用于挂载**外部资料合集**（不复制文件，原地索引），
    避免把几百 MB 的资料拷进项目目录。
    """
    texts: list[tuple[str, str, str]] = []

    # 1) JSONL 知识库（权威、精炼，doc_id 由作者指定）
    if docs_file and os.path.isfile(docs_file):
        with open(docs_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rd = json.loads(line)
                content = rd.get("content", "")
                if content and content.strip():
                    texts.append((content, rd.get("doc_id", "doc"), rd.get("source", "")))

    # 2) 项目内文档目录
    if dir_path and os.path.isdir(dir_path):
        texts.extend(_collect_dir_texts(dir_path, recursive=recursive))

    # 3) 外部资料目录（原地索引）
    for extra in (extra_dirs or []):
        if not extra or not os.path.isdir(extra):
            if extra:
                print(f"  跳过外部目录（不存在）：{extra}")
            continue
        got = _collect_dir_texts(extra, recursive=recursive)
        print(f"  外部目录 {extra} → {len(got)} 个可解析文件")
        texts.extend(got)

    if not texts:
        print("没有可索引的内容")
        return 0
    return _chunk_and_index(texts, chunk_size)


def ab_test(docs_file: str, chunk_sizes: list[int]) -> dict:
    """Chunk Size A/B：对比不同 chunk 下的分块统计。"""
    import statistics
    with open(docs_file, encoding="utf-8") as f:
        raw = [json.loads(line) for line in f if line.strip()]

    report = {}
    for cs in chunk_sizes:
        splitter = _splitter(cs)
        counts, lengths = [], []
        for rd in raw:
            chunks = splitter.split_text(rd.get("content", ""))
            counts.append(len(chunks))
            lengths += [len(c) for c in chunks]
        report[str(cs)] = {
            "avg_chunks_per_doc": round(statistics.mean(counts), 2),
            "avg_chunk_len": round(statistics.mean(lengths), 1) if lengths else 0,
        }
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--docs", required=True)
    b.add_argument("--chunk", type=int, default=200)
    d = sub.add_parser("build_dir")
    d.add_argument("--dir", required=True)
    d.add_argument("--chunk", type=int, default=200)
    ba = sub.add_parser("build_all")
    ba.add_argument("--docs", default="data/knowledge.jsonl")
    ba.add_argument("--dir", default="data/docs")
    ba.add_argument("--chunk", type=int, default=None,
                    help="分块大小；不填则用 .env 的 RAG_CHUNK_SIZE")
    ba.add_argument("--extra", nargs="*", default=[],
                    help="额外资料目录（可多个，原地索引，不复制文件）")
    ba.add_argument("--no-extra", action="store_true",
                    help="忽略配置/环境变量里的外部资料目录，只索引项目内资料（快速）")
    ba.add_argument("--no-recursive", action="store_true",
                    help="不递归子目录（默认递归）")
    a = sub.add_parser("abtest")
    a.add_argument("--docs", required=True)
    a.add_argument("--chunks", type=int, nargs="+", default=[100, 200, 500])
    args = ap.parse_args()
    if args.cmd == "build":
        print(f"已建索引：{build_index(args.docs, args.chunk)} 块")
    elif args.cmd == "build_dir":
        print(f"已建索引：{build_index_from_dir(args.dir, args.chunk)} 块")
    elif args.cmd == "build_all":
        if args.no_extra:
            print("已指定 --no-extra：只索引项目内资料（跳过外部资料合集）")
            extra: list[str] = []
        else:
            # 外部资料目录来源（按优先级）：命令行 --extra > 环境变量 EXTRA_DOCS_DIRS > .env 配置
            extra = list(args.extra or [])
            env_extra = os.getenv("EXTRA_DOCS_DIRS", "")
            if env_extra:
                extra += [d for d in env_extra.split(";") if d.strip()]
            try:
                from app.config import get_settings

                cfg_extra = get_settings().extra_docs_dirs or ""
                if cfg_extra:
                    extra += [d.strip() for d in cfg_extra.split(";") if d.strip()]
            except Exception:  # noqa: BLE001
                pass
        # 去重且保持顺序
        seen: set[str] = set()
        extra = [d for d in extra if not (d in seen or seen.add(d))]

        if extra:
            print("外部资料目录：")
            for d in extra:
                print(f"  - {d}")
        else:
            print("未配置外部资料目录（仅索引知识库 + data/docs）")

        n = build_all(args.docs, args.dir, _resolve_chunk_size(args.chunk),
                      extra_dirs=extra, recursive=not args.no_recursive)
        print(f"已建索引（知识库 + 文档目录 + 外部资料）：{n} 块（chunk={_resolve_chunk_size(args.chunk)}）")
    else:
        print(json.dumps(ab_test(args.docs, args.chunks), ensure_ascii=False, indent=2))
