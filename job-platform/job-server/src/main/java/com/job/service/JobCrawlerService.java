package com.job.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.job.entity.Company;
import com.job.entity.Job;
import com.job.entity.JobCategory;
import com.job.mapper.CompanyMapper;
import com.job.mapper.JobCategoryMapper;
import com.job.mapper.JobMapper;
import com.job.properties.CrawlProperties;
import com.job.utils.HttpClientUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 国企/央企招聘岗位爬虫（多数据源，支持 GET/POST，JSON 自动识别字段）
 */
@Service
@Slf4j
public class JobCrawlerService {

    @Autowired
    private CrawlProperties crawlProperties;
    @Autowired
    private CompanyMapper companyMapper;
    @Autowired
    private JobMapper jobMapper;
    @Autowired
    private JobCategoryMapper jobCategoryMapper;
    /** 手动清缓存用：爬虫这条写入路径绕过了 Service 代理，@CacheEvict 不会触发。 */
    @Autowired
    private JobCacheService jobCacheService;

    private static final String UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36";

    private static final String[] TITLE_KEYS = {"jobName", "job_name", "positionName", "postName", "title", "name", "岗位名称", "职位名称"};
    private static final String[] COMPANY_KEYS = {"recName", "companyName", "company_name", "company", "enterpriseName", "corpName", "unitName", "orgName", "公司名称", "单位名称"};
    private static final String[] CITY_KEYS = {"areaCodeName", "city", "workCity", "workPlace", "address", "工作地点", "城市"};
    private static final String[] SALARY_KEYS = {"salary", "salaryText", "pay", "salaryRange", "薪资", "薪酬"};
    private static final String[] EDU_KEYS = {"degreeName", "education_cn", "education", "degree", "eduRequirement", "degreeRequirement", "学历", "学历要求"};
    private static final String[] TAG_KEYS = {"recTags", "category_cn", "tags", "welfare", "福利"};
    private static final String[] DESC_KEYS = {"contents", "description", "jobDesc", "岗位描述", "职位描述"};
    private static final String[] COMPANY_TYPE_KEYS = {"recProperty", "companyProperty", "companyType", "enterpriseType", "企业性质"};
    private static final String[] CATEGORY_KEYS = {"category_cn", "category", "jobCategory", "岗位类别", "major"};
    private static final String[] JOB_ID_KEYS = {"jobId", "job_id", "id"};

    /** 任职要求段落标题关键词（覆盖各种表述） */
    private static final String[] REQUIREMENT_MARKERS = {
            "任职条件", "任职要求", "任职资格", "任职标准", "任职能力要求",
            "岗位要求", "岗位条件", "岗位资格", "岗位任职要求",
            "职位要求", "招聘要求", "招聘条件", "招聘标准", "招聘对象",
            "应聘要求", "应聘条件", "应聘资格",
            "报名条件", "报名要求",
            "资格要求", "任职资格要求",
            "能力要求", "基本要求", "基本条件", "工作要求", "录用条件", "录用标准",
            "其他要求", "胜任要求", "胜任力要求", "资质要求", "优先条件",
            "学历要求", "专业要求", "经验要求", "工作经验要求"
    };

    /** 任职要求标题行匹配：行首 + 可选序号(一、/1.) + 可选括号【】（) + 可选冒号 */
    private static final Pattern REQUIREMENT_HEADER = Pattern.compile(
            "(?m)^[ \\t]*(?:[一二三四五六七八九十\\d]+[、.．:：]\\s*)?[【\\[（(]?\\s*(" +
                    String.join("|", REQUIREMENT_MARKERS) + ")\\s*[】\\]）)]?\\s*[:：]?"
    );

    // 分类关键词规则：分类名 -> 关键词（按顺序匹配，先匹配先归）
    private static final String[][] CATEGORY_RULES = {
            {"技术研发", "技术,软件,开发,算法,测试,工程师,IT,信息,数据,人工智能,AI,编程,前端,后端,运维,网络,计算机,电子,研发,设计,仿真,科研,数字化,智能制造,自动化,产品,图像,光学,卫星,飞行器,航天,宇航,知识工程,数智,售前,售后,算力,云,大数据,智慧"},
            {"财务审计", "财务,会计,审计,税务,核算,出纳,资金,结算"},
            {"金融投资", "金融,投资,银行,证券,基金,保险,经济,风控"},
            {"法律合规", "法律,法务,合规,纪检,监察,巡察"},
            {"市场营销", "市场,营销,销售,品牌,运营,策划,商务,客户,拓展,业务,采购"},
            {"行政人力", "行政,人力,人事,文秘,党务,宣传,管培生,储备干部,综合管理,职能管理,管理类"},
            {"工程制造", "工程,制造,能源,电气,机械,化工,地质,建筑,勘探,焊接,材料,矿业,石油,电力,仪表,生产,设备,检测,质检,品质,供应链,物流,操作,运行,航空,船务,医药,医学,环保,抽样,巡检,热泵,实验,储层,风洞,养殖,农,牧,渔"}
    };

    /** 调度入口：遍历所有数据源 */
    public int crawl() {
        int count = 0;
        for (CrawlProperties.Source source : crawlProperties.getSources()) {
            try {
                count += crawlSource(source);
            } catch (Exception e) {
                log.error("数据源 {} 爬取异常：{}", source.getUrl(), e.getMessage(), e);
            }
        }
        log.info("本次爬取完成，共新增 {} 个岗位", count);
        return count;
    }

    private int crawlSource(CrawlProperties.Source source) {
        int count = 0;
        String[] properties = (source.getPropertyList() == null || source.getPropertyList().isEmpty())
                ? new String[]{""} : source.getPropertyList().split(",");
        for (String property : properties) {
            for (int page = 1; page <= source.getMaxPages(); page++) {
                try {
                    String json = "POST".equalsIgnoreCase(source.getMethod())
                            ? fetchPost(source, page, source.getPageSize())
                            : fetchGet(source, property.trim(), page, source.getPageSize());
                    if (json == null || json.isEmpty()) break;
                    Object parsed = JSON.parse(json);
                    List<JSONObject> items = findObjectList(parsed);
                    if (items == null || items.isEmpty()) break;
                    for (JSONObject item : items) {
                        String title = findStr(item, TITLE_KEYS);
                        String companyName = findStr(item, COMPANY_KEYS);
                        String companyType = findStr(item, COMPANY_TYPE_KEYS);
                        String city = extractCity(item);
                        String education = findStr(item, EDU_KEYS);
                        String tags = extractTags(item);
                        String[] descReq = splitDescriptionRequirement(findStr(item, DESC_KEYS));
                        String description = descReq[0];
                        String requirement = descReq[1];
                        int[] salary = extractSalary(item);
                        Long categoryId = resolveCategoryId(title, companyName, findStr(item, CATEGORY_KEYS));
                        String sourceUrl = buildSourceUrl(source, item);
                        if (!isTargetCompany(source, companyType)) continue;
                        if (title == null || companyName == null) continue;
                        count += saveJob(title, companyName, companyType, city, education, tags, description, requirement, salary, categoryId, sourceUrl);
                    }
                    Thread.sleep(500);
                } catch (Exception e) {
                    log.error("数据源 {} 第 {} 页失败：{}", source.getUrl(), page, e.getMessage());
                    break;
                }
            }
        }
        return count;
    }

    private String fetchGet(CrawlProperties.Source source, String property, int page, int pageSize) {
        String url = source.getUrl();
        if (property != null && !property.isEmpty()) {
            try {
                String encoded = java.net.URLEncoder.encode(property, "UTF-8");
                url = url.replaceAll("property=[^&]*", "property=" + encoded);
            } catch (Exception ignored) {
            }
        }
        url = url.replaceAll("offset=\\d+", "offset=" + page);
        url = url.replaceAll("limit=\\d+", "limit=" + pageSize);
        url = url.replaceAll("[&?]_=\\d+", "");
        return HttpClientUtil.doGetWithHeaders(url, null, buildHeaders(source));
    }

    private String fetchPost(CrawlProperties.Source source, int page, int pageSize) {
        String body = source.getBody();
        if (body != null) {
            body = body.replaceAll("\"page\":\\d+", "\"page\":" + page);
            body = body.replaceAll("\"page_size\":\\d+", "\"page_size\":" + pageSize);
        }
        return HttpClientUtil.doPostJsonWithHeaders(source.getUrl(), body, buildHeaders(source));
    }

    private Map<String, String> buildHeaders(CrawlProperties.Source source) {
        Map<String, String> headers = new HashMap<>();
        headers.put("User-Agent", UA);
        headers.put("Accept", "application/json, text/plain, */*");
        if (source.getReferer() != null) headers.put("Referer", source.getReferer());
        if (source.getOrigin() != null) headers.put("Origin", source.getOrigin());
        if (source.getDevice() != null) headers.put("device", source.getDevice());
        if (source.getSubsite() != null) headers.put("subsite", source.getSubsite());
        headers.put("X-Requested-With", "XMLHttpRequest");
        return headers;
    }

    /** 保存岗位，返回是否新增（0/1） */
    private int saveJob(String title, String companyName, String companyType, String city, String education, String tags, String description, String requirement, int[] salary, Long categoryId, String sourceUrl) {
        if (title == null || title.isEmpty() || companyName == null || companyName.isEmpty()) return 0;
        Company company = companyMapper.getByName(companyName);
        if (company == null) {
            company = new Company();
            company.setName(companyName);
            company.setCity(city);
            company.setType(companyType);
            company.setStatus(1);
            company.setCreateTime(LocalDateTime.now());
            company.setUpdateTime(LocalDateTime.now());
            companyMapper.insert(company);
        }
        Job existing = jobMapper.getByTitleAndCompanyId(title, company.getId());
        if (existing != null) {
            jobMapper.refreshCrawlContent(existing.getId(), description, requirement, sourceUrl);
            // ★ 缓存一致性：这条路径**直接调 Mapper**，没经过 JobServiceImpl 的代理，
            //   所以上面的 @CacheEvict 完全不会触发。不主动清的话，
            //   job:detail:{id} 会一直是爬虫改写之前的旧描述（最长脏到 TTL 过期）。
            //   顺序遵循 Cache Aside：先写库（上面这行已提交），再删缓存。
            jobCacheService.evictDetail(existing.getId());
            return 0;
        }
        Job job = new Job();
        job.setCompanyId(company.getId());
        job.setTitle(title);
        job.setCity(city);
        job.setEducation(education);
        job.setSalaryMin(salary[0]);
        job.setSalaryMax(salary[1]);
        job.setTags(tags);
        job.setDescription(description);
        job.setRequirement(requirement);
        job.setCategoryId(categoryId);
        job.setSourceUrl(sourceUrl);
        job.setStatus(1);
        job.setViewCount(0);
        job.setApplyCount(0);
        job.setCreateTime(LocalDateTime.now());
        job.setUpdateTime(LocalDateTime.now());
        jobMapper.insert(job);
        return 1;
    }

    /** 把「岗位职责 + 任职要求」混在一段的原文拆成两个字段 */
    private String[] splitDescriptionRequirement(String raw) {
        if (raw == null || raw.isEmpty()) return new String[]{null, null};
        String text = raw.trim();
        Matcher m = REQUIREMENT_HEADER.matcher(text);
        if (!m.find()) return new String[]{text, null};
        int idx = m.start();
        String desc = text.substring(0, idx).trim();
        String req = text.substring(idx).trim();
        return new String[]{desc.isEmpty() ? null : desc, req.isEmpty() ? null : req};
    }

    private boolean isTargetCompany(CrawlProperties.Source source, String type) {
        if (type == null || type.isEmpty()) return true;
        String filter = source.getCompanyTypeFilter();
        if (filter == null || filter.isEmpty()) return true;
        for (String kw : filter.split(",")) {
            if (type.contains(kw.trim())) return true;
        }
        return false;
    }

    private String extractCity(JSONObject item) {
        String city = findStr(item, CITY_KEYS);
        if (city != null) return city;
        JSONArray districtList = item.getJSONArray("district_list");
        if (districtList != null && !districtList.isEmpty()) {
            JSONObject first = districtList.getJSONObject(0);
            if (first != null) {
                String c = first.getString("area_cn");
                if (c == null || c.isEmpty()) c = first.getString("city");
                return c;
            }
        }
        return null;
    }

    private String extractTags(JSONObject item) {
        String tags = findStr(item, TAG_KEYS);
        if (tags != null) return tags;
        JSONArray majors = item.getJSONArray("major_cn");
        if (majors != null && !majors.isEmpty()) {
            List<String> list = new ArrayList<>();
            for (int i = 0; i < majors.size(); i++) list.add(majors.getString(i));
            return String.join(",", list);
        }
        return null;
    }

    private int[] extractSalary(JSONObject item) {
        Object minW = item.get("min_wage");
        Object maxW = item.get("max_wage");
        if (minW instanceof Number && maxW instanceof Number) {
            return new int[]{((Number) minW).intValue(), ((Number) maxW).intValue()};
        }
        Object low = item.get("lowMonthPay");
        Object high = item.get("highMonthPay");
        if (low instanceof Number && high instanceof Number) {
            return new int[]{(int) (((Number) low).doubleValue() * 1000), (int) (((Number) high).doubleValue() * 1000)};
        }
        return parseSalary(findStr(item, SALARY_KEYS));
    }

    /** 根据分类提示词匹配分类名 */
    private String matchCategoryName(String hint) {
        if (hint == null || hint.isEmpty()) return "综合其他";
        for (String[] rule : CATEGORY_RULES) {
            String name = rule[0];
            for (String kw : rule[1].split(",")) {
                if (hint.contains(kw)) return name;
            }
        }
        return "综合其他";
    }

    /** 解析分类 id（结合岗位名、公司名、分类提示词） */
    private Long resolveCategoryId(String title, String companyName, String hint) {
        String text = (title == null ? "" : title) + " " + (companyName == null ? "" : companyName) + " " + (hint == null ? "" : hint);
        String name = matchCategoryName(text);
        JobCategory category = jobCategoryMapper.getByName(name);
        return category == null ? null : category.getId();
    }

    /** 根据 URL 模板构造岗位详情页地址 */
    private String buildSourceUrl(CrawlProperties.Source source, JSONObject item) {
        String template = source.getJobUrlTemplate();
        if (template == null || template.isEmpty()) return null;
        String jobId = findStr(item, JOB_ID_KEYS);
        if (jobId == null || jobId.isEmpty()) return null;
        return template.replace("{jobId}", jobId);
    }

    private List<JSONObject> findObjectList(Object obj) {
        if (obj instanceof JSONArray) {
            JSONArray arr = (JSONArray) obj;
            List<JSONObject> list = new ArrayList<>();
            for (int i = 0; i < arr.size(); i++) {
                Object o = arr.get(i);
                if (o instanceof JSONObject) list.add((JSONObject) o);
            }
            return list.isEmpty() ? null : list;
        }
        if (obj instanceof JSONObject) {
            JSONObject jo = (JSONObject) obj;
            List<JSONObject> best = null;
            for (String key : jo.keySet()) {
                Object v = jo.get(key);
                if (v instanceof JSONArray) {
                    List<JSONObject> candidate = new ArrayList<>();
                    for (int i = 0; i < ((JSONArray) v).size(); i++) {
                        Object o = ((JSONArray) v).get(i);
                        if (o instanceof JSONObject) candidate.add((JSONObject) o);
                    }
                    if (!candidate.isEmpty() && (best == null || candidate.size() > best.size())) best = candidate;
                } else if (v instanceof JSONObject) {
                    List<JSONObject> candidate = findObjectList(v);
                    if (candidate != null && (best == null || candidate.size() > best.size())) best = candidate;
                }
            }
            return best;
        }
        return null;
    }

    private String findStr(JSONObject obj, String[] keys) {
        for (String k : keys) {
            Object v = obj.get(k);
            if (v != null && !v.toString().trim().isEmpty()) return v.toString().trim();
        }
        return null;
    }

    private int[] parseSalary(String text) {
        if (text == null || text.isEmpty()) return new int[]{0, 0};
        Matcher m = Pattern.compile("(\\d+(?:\\.\\d+)?)\\s*[-~至]\\s*(\\d+(?:\\.\\d+)?)\\s*([kK千wW万]?)").matcher(text);
        if (m.find()) {
            try {
                double min = Double.parseDouble(m.group(1));
                double max = Double.parseDouble(m.group(2));
                String unit = m.group(3);
                int factor = 1000;
                if ("万".equals(unit) || "w".equalsIgnoreCase(unit)) factor = 10000;
                if (max < 100) {
                    min *= factor;
                    max *= factor;
                }
                return new int[]{(int) min, (int) max};
            } catch (Exception ignored) {
            }
        }
        return new int[]{0, 0};
    }
}
