package com.job.service.impl;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.job.constant.MessageConstant;
import com.job.constant.StatusConstant;
import com.job.dto.CompanyDTO;
import com.job.dto.CompanyPageQueryDTO;
import com.job.entity.Company;
import com.job.exception.DeletionNotAllowedException;
import com.job.mapper.CompanyMapper;
import com.job.mapper.JobMapper;
import com.job.result.PageResult;
import com.job.service.CompanyService;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class CompanyServiceImpl implements CompanyService {

    @Autowired
    private CompanyMapper companyMapper;
    @Autowired
    private JobMapper jobMapper;

    @Override
    public void save(CompanyDTO companyDTO) {
        Company company = new Company();
        BeanUtils.copyProperties(companyDTO, company);
        company.setStatus(StatusConstant.ENABLE);
        company.setCreateTime(LocalDateTime.now());
        company.setUpdateTime(LocalDateTime.now());
        companyMapper.insert(company);
    }

    @Override
    public PageResult pageQuery(CompanyPageQueryDTO companyPageQueryDTO) {
        PageHelper.startPage(companyPageQueryDTO.getPage(), companyPageQueryDTO.getPageSize());
        Page<Company> page = companyMapper.pageQuery(companyPageQueryDTO);
        return new PageResult(page.getTotal(), page.getResult());
    }

    @Override
    public void deleteById(Long id) {
        Integer count = jobMapper.countByCompanyId(id);
        if (count != null && count > 0) {
            throw new DeletionNotAllowedException(MessageConstant.COMPANY_BE_RELATED_BY_JOB);
        }
        companyMapper.deleteById(id);
    }

    @Override
    public Company getById(Long id) {
        return companyMapper.getById(id);
    }

    @Override
    public void update(CompanyDTO companyDTO) {
        Company company = new Company();
        BeanUtils.copyProperties(companyDTO, company);
        company.setUpdateTime(LocalDateTime.now());
        companyMapper.update(company);
    }

    @Override
    public List<Company> list() {
        return companyMapper.listAll();
    }
}
