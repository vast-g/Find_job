package com.job.controller.user;

import com.job.entity.Company;
import com.job.result.Result;
import com.job.service.CompanyService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController("userCompanyController")
@RequestMapping("/user/company")
@Api(tags = "C端企业接口")
@Slf4j
public class CompanyController {

    @Autowired
    private CompanyService companyService;

    @GetMapping("/{id}")
    @ApiOperation("企业详情")
    public Result<Company> getById(@PathVariable Long id) {
        return Result.success(companyService.getById(id));
    }
}
