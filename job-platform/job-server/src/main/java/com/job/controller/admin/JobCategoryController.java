package com.job.controller.admin;

import com.job.dto.JobCategoryDTO;
import com.job.entity.JobCategory;
import com.job.result.PageResult;
import com.job.result.Result;
import com.job.service.JobCategoryService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/admin/category")
@Api(tags = "岗位分类相关接口")
@Slf4j
public class JobCategoryController {

    @Autowired
    private JobCategoryService jobCategoryService;

    @PostMapping
    @ApiOperation("新增分类")
    public Result save(@RequestBody JobCategoryDTO jobCategoryDTO) {
        jobCategoryService.save(jobCategoryDTO);
        return Result.success();
    }

    @PutMapping
    @ApiOperation("修改分类")
    public Result update(@RequestBody JobCategoryDTO jobCategoryDTO) {
        jobCategoryService.update(jobCategoryDTO);
        return Result.success();
    }

    @DeleteMapping("/{id}")
    @ApiOperation("删除分类")
    public Result deleteById(@PathVariable Long id) {
        jobCategoryService.deleteById(id);
        return Result.success();
    }

    @GetMapping("/page")
    @ApiOperation("分类分页查询")
    public Result<PageResult> page(JobCategoryDTO jobCategoryDTO) {
        return Result.success(jobCategoryService.pageQuery(jobCategoryDTO));
    }

    @GetMapping("/list")
    @ApiOperation("分类列表")
    public Result<List<JobCategory>> list() {
        return Result.success(jobCategoryService.list());
    }

    @GetMapping("/{id}")
    @ApiOperation("分类详情")
    public Result<JobCategory> getById(@PathVariable Long id) {
        return Result.success(jobCategoryService.getById(id));
    }

    @PostMapping("/status/{status}")
    @ApiOperation("启用禁用分类")
    public Result startOrStop(@PathVariable Integer status, Long id) {
        jobCategoryService.startOrStop(status, id);
        return Result.success();
    }
}
