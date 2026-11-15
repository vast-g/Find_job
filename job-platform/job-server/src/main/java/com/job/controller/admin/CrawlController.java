package com.job.controller.admin;

import com.job.result.Result;
import com.job.service.JobCrawlerService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController("adminCrawlController")
@RequestMapping("/admin/crawl")
@Api(tags = "爬虫管理接口")
public class CrawlController {

    @Autowired
    private JobCrawlerService jobCrawlerService;

    @PostMapping("/run")
    @ApiOperation("手动触发一次爬取")
    public Result<Integer> run() {
        int count = jobCrawlerService.crawl();
        return Result.success(count);
    }
}
