package com.job.controller.user;

import com.job.entity.JobCategory;
import com.job.result.Result;
import com.job.service.JobCategoryService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController("userCategoryController")
@RequestMapping("/user/category")
@Api(tags = "C端分类接口")
@Slf4j
public class CategoryController {

    @Autowired
    private JobCategoryService jobCategoryService;

    @GetMapping("/list")
    @ApiOperation("分类列表")
    public Result<List<JobCategory>> list() {
        return Result.success(jobCategoryService.list());
    }
}
