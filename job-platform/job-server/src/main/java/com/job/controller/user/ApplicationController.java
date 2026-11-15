package com.job.controller.user;

import com.job.dto.ApplicationSubmitDTO;
import com.job.result.Result;
import com.job.service.ApplicationService;
import com.job.vo.ApplicationVO;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController("userApplicationController")
@RequestMapping("/user/application")
@Api(tags = "C端投递接口")
@Slf4j
public class ApplicationController {

    @Autowired
    private ApplicationService applicationService;

    @PostMapping("/submit")
    @ApiOperation("投递岗位")
    public Result submit(@RequestBody ApplicationSubmitDTO applicationSubmitDTO) {
        applicationService.submit(applicationSubmitDTO);
        return Result.success();
    }

    @GetMapping("/my")
    @ApiOperation("我的投递")
    public Result<List<ApplicationVO>> my() {
        return Result.success(applicationService.myList());
    }

    @PutMapping("/cancel/{id}")
    @ApiOperation("取消投递")
    public Result cancel(@PathVariable Long id) {
        applicationService.cancel(id);
        return Result.success();
    }
}
