package com.job.controller.user;

import com.job.result.Result;
import com.job.service.JobFavoriteService;
import com.job.vo.JobVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/user/favorite")
@Api(tags = "C端岗位收藏接口")
@Slf4j
public class FavoriteController {

    @Autowired
    private JobFavoriteService jobFavoriteService;

    @PostMapping("/{jobId}")
    @ApiOperation("收藏岗位")
    public Result add(@PathVariable Long jobId) {
        jobFavoriteService.add(jobId);
        return Result.success();
    }

    @DeleteMapping("/{jobId}")
    @ApiOperation("取消收藏")
    public Result cancel(@PathVariable Long jobId) {
        jobFavoriteService.cancel(jobId);
        return Result.success();
    }

    @GetMapping("/list")
    @ApiOperation("我的收藏")
    public Result<List<JobVO>> list() {
        return Result.success(jobFavoriteService.list());
    }
}
