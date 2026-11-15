package com.job.controller.admin;

import com.job.dto.JobDTO;
import com.job.dto.JobPageQueryDTO;
import com.job.result.PageResult;
import com.job.result.Result;
import com.job.service.JobService;
import com.job.vo.JobVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/admin/job")
@Api(tags = "岗位管理相关接口")
@Slf4j
public class JobController {

    @Autowired
    private JobService jobService;

    @PostMapping
    @ApiOperation("新增岗位")
    public Result save(@RequestBody JobDTO jobDTO) {
        jobService.save(jobDTO);
        return Result.success();
    }

    @PutMapping
    @ApiOperation("修改岗位")
    public Result update(@RequestBody JobDTO jobDTO) {
        jobService.update(jobDTO);
        return Result.success();
    }

    @DeleteMapping
    @ApiOperation("批量删除岗位")
    public Result delete(@RequestParam List<Long> ids) {
        jobService.deleteBatch(ids);
        return Result.success();
    }

    @GetMapping("/page")
    @ApiOperation("岗位分页查询")
    public Result<PageResult> page(JobPageQueryDTO jobPageQueryDTO) {
        return Result.success(jobService.pageQuery(jobPageQueryDTO));
    }

    @GetMapping("/{id}")
    @ApiOperation("岗位详情")
    public Result<JobVO> getById(@PathVariable Long id) {
        return Result.success(jobService.getById(id));
    }

    @PostMapping("/status/{status}")
    @ApiOperation("岗位上下架")
    public Result startOrStop(@PathVariable Integer status, Long id) {
        jobService.startOrStop(status, id);
        return Result.success();
    }
}
