package com.job.service;

import com.job.dto.CompanyDTO;
import com.job.dto.CompanyPageQueryDTO;
import com.job.entity.Company;
import com.job.result.PageResult;

import java.util.List;

public interface CompanyService {

    void save(CompanyDTO companyDTO);

    PageResult pageQuery(CompanyPageQueryDTO companyPageQueryDTO);

    void deleteById(Long id);

    Company getById(Long id);

    void update(CompanyDTO companyDTO);

    List<Company> list();
}
