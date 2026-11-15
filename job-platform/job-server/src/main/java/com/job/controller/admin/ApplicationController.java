package com.job.controller.admin;

import com.job.dto.ApplicationPageQueryDTO;
import com.job.result.PageResult;
import com.job.result.Result;
import com.job.service.ApplicationService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;

@RestController("adminApplicationController")
@RequestMapping("/admin/application")
@Api(tags = "投递管理相关接口")
@Slf4j
public class ApplicationController {

    @Autowired
    private ApplicationService applicationService;

    @GetMapping("/page")
    @ApiOperation("投递分页查询")
    public Result<PageResult> page(ApplicationPageQueryDTO applicationPageQueryDTO) {
        return Result.success(applicationService.pageQuery(applicationPageQueryDTO));
    }

    @PostMapping("/status/{status}")
    @ApiOperation("更新投递状态")
    public Result updateStatus(@PathVariable Integer status,
                               @RequestParam Long id,
                               @RequestParam(required = false) String remark,
                               @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd HH:mm:ss") LocalDateTime interviewTime) {
        applicationService.updateStatus(id, status, remark, interviewTime);
        return Result.success();
    }
}
