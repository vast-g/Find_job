package com.job.controller.admin;

import com.job.dto.CompanyDTO;
import com.job.dto.CompanyPageQueryDTO;
import com.job.entity.Company;
import com.job.result.PageResult;
import com.job.result.Result;
import com.job.service.CompanyService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/admin/company")
@Api(tags = "企业相关接口")
@Slf4j
public class CompanyController {

    @Autowired
    private CompanyService companyService;

    @PostMapping
    @ApiOperation("新增企业")
    public Result save(@RequestBody CompanyDTO companyDTO) {
        companyService.save(companyDTO);
        return Result.success();
    }

    @PutMapping
    @ApiOperation("修改企业")
    public Result update(@RequestBody CompanyDTO companyDTO) {
        companyService.update(companyDTO);
        return Result.success();
    }

    @DeleteMapping("/{id}")
    @ApiOperation("删除企业")
    public Result deleteById(@PathVariable Long id) {
        companyService.deleteById(id);
        return Result.success();
    }

    @GetMapping("/page")
    @ApiOperation("企业分页查询")
    public Result<PageResult> page(CompanyPageQueryDTO companyPageQueryDTO) {
        return Result.success(companyService.pageQuery(companyPageQueryDTO));
    }

    @GetMapping("/list")
    @ApiOperation("企业列表")
    public Result<List<Company>> list() {
        return Result.success(companyService.list());
    }

    @GetMapping("/{id}")
    @ApiOperation("企业详情")
    public Result<Company> getById(@PathVariable Long id) {
        return Result.success(companyService.getById(id));
    }
}
