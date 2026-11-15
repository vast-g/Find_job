package com.job.controller.user;

import com.job.constant.StatusConstant;
import com.job.entity.Job;
import com.job.result.Result;
import com.job.service.JobService;
import com.job.vo.JobVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController("userJobController")
@RequestMapping("/user/job")
@Api(tags = "C端岗位浏览接口")
@Slf4j
public class JobController {

    @Autowired
    private JobService jobService;

    @GetMapping("/list")
    @ApiOperation("岗位列表")
    public Result<List<JobVO>> list(Long categoryId, String city, String education, String keyword) {
        Job job = Job.builder()
                .categoryId(categoryId)
                .city(city)
                .education(education)
                .title(keyword)
                .status(StatusConstant.ENABLE)
                .build();
        return Result.success(jobService.listByCondition(job));
    }

    @GetMapping("/{id}")
    @ApiOperation("岗位详情")
    public Result<JobVO> getById(@PathVariable Long id) {
        return Result.success(jobService.getById(id));
    }
}
