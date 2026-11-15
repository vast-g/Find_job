package com.job.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
@ConfigurationProperties(prefix = "job.crawl")
@Data
public class CrawlProperties {

    /** 是否启用爬虫 */
    private boolean enabled = false;

    /** 定时 cron 表达式，默认每天 6 点 */
    private String cron = "0 0 6 * * ?";

    /** 多个数据源 */
    private List<Source> sources = new ArrayList<>();

    @Data
    public static class Source {
        /** 接口/页面地址 */
        private String url;
        /** GET / POST */
        private String method = "GET";
        /** POST 请求体（JSON 字符串） */
        private String body;
        /** Referer 头 */
        private String referer;
        /** Origin 头 */
        private String origin;
        /** device 头 */
        private String device = "pc";
        /** subsite 头 */
        private String subsite;
        /** 企业性质列表（逗号分隔），逐个作为 property 参数爬取（job.ncss.cn 用） */
        private String propertyList;
        /** 企业性质过滤关键词（逗号分隔） */
        private String companyTypeFilter = "国有,央企,事业";
        /** 每页条数 */
        private int pageSize = 10;
        /** 最大爬取页数 */
        private int maxPages = 10;
        /** 岗位详情页 URL 模板，{jobId} 会被替换 */
        private String jobUrlTemplate;
    }
}
