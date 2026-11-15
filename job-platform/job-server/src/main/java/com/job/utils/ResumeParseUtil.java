package com.job.utils;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 简历解析：提取 Word/PDF 文本 + 简单规则解析结构化字段
 */
public class ResumeParseUtil {

    public static String extractText(MultipartFile file) throws Exception {
        byte[] bytes = file.getBytes();
        if (isPdf(bytes)) {
            try (PDDocument doc = PDDocument.load(bytes)) {
                return new PDFTextStripper().getText(doc);
            }
        } else if (isDocx(bytes)) {
            return extractDocxText(bytes);
        }
        throw new RuntimeException("仅支持 Word(.docx) 或 PDF 格式");
    }

    private static boolean isPdf(byte[] b) {
        return b != null && b.length > 4 && b[0] == '%' && b[1] == 'P' && b[2] == 'D' && b[3] == 'F';
    }

    private static boolean isDocx(byte[] b) {
        return b != null && b.length > 2 && b[0] == 'P' && b[1] == 'K';
    }

    /**
     * 解析 docx 的 document.xml，提取所有 w:t 文本（含文本框、表格）
     */
    private static String extractDocxText(byte[] bytes) throws Exception {
        try (ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                if ("word/document.xml".equals(entry.getName())) {
                    String xml = readAll(zis);
                    StringBuilder sb = new StringBuilder();
                    Matcher m = Pattern.compile("<w:t(?:\\s[^>]*)?>([^<]*)</w:t>").matcher(xml);
                    while (m.find()) {
                        sb.append(unescape(m.group(1))).append("\n");
                    }
                    return sb.toString().trim();
                }
            }
        }
        throw new RuntimeException("无法解析 Word 文档");
    }

    private static String readAll(ZipInputStream zis) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = zis.read(buf)) != -1) {
            out.write(buf, 0, n);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

    private static String unescape(String s) {
        return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&apos;", "'").replace("&#10;", "\n");
    }

    public static Map<String, Object> parse(String text) {
        Map<String, Object> map = new HashMap<>();
        if (text == null) text = "";
        String t = text.replace("\r", "").trim();
        map.put("rawText", t);
        map.put("name", matchName(t));
        map.put("age", matchAge(t));
        map.put("education", matchEdu(t));
        map.put("educationExperience", section(t, "教育经历", "项目经历"));
        map.put("projectExperience", section(t, "项目经历", "校园经历"));
        map.put("campusExperience", section(t, "校园经历", null));
        return map;
    }

    private static String matchName(String text) {
        // 容忍标签内换行/空格：姓 名：郭俊辉
        Matcher m = Pattern.compile("姓\\s*名\\s*[:：]\\s*([\\u4e00-\\u9fa5]{2,4})").matcher(text);
        if (m.find()) return m.group(1);
        for (String line : text.split("\n")) {
            String s = line.trim();
            if (s.length() >= 2 && s.length() <= 3 && s.matches("[\\u4e00-\\u9fa5]+") && !s.equals("个人简历")) {
                return s;
            }
        }
        return null;
    }

    private static String matchAge(String text) {
        String a = match(text, "年龄\\s*[:：]\\s*(\\d{1,2})");
        if (a != null) return a;
        String y = match(text, "出生年月\\s*[:：]\\s*(\\d{4})");
        if (y != null) {
            try {
                int year = Integer.parseInt(y);
                int now = java.time.LocalDate.now().getYear();
                return String.valueOf(now - year);
            } catch (Exception ignored) {
            }
        }
        return match(text, "(\\d{2})\\s*岁");
    }

    private static String matchEdu(String text) {
        Matcher m = Pattern.compile("学\\s*历\\s*[:：]\\s*([\\u4e00-\\u9fa5]{2,6})").matcher(text);
        if (m.find()) return m.group(1);
        if (text.contains("博士")) return "博士";
        if (text.contains("硕士")) return "硕士";
        if (text.contains("本科")) return "本科";
        if (text.contains("大专")) return "大专";
        return null;
    }

    private static String match(String text, String regex) {
        Matcher m = Pattern.compile(regex).matcher(text);
        return m.find() ? m.group(1) : null;
    }

    private static String section(String text, String start, String end) {
        int s = text.indexOf(start);
        if (s < 0) return null;
        int e = end == null ? text.length() : text.indexOf(end, s);
        if (e < 0) e = text.length();
        return text.substring(s + start.length(), e).trim();
    }
}
