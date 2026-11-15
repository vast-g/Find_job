package com.job.mapper;

import com.github.pagehelper.Page;
import com.job.dto.CompanyPageQueryDTO;
import com.job.entity.Company;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CompanyMapper {

    void insert(Company company);

    Page<Company> pageQuery(CompanyPageQueryDTO companyPageQueryDTO);

    @Select("select * from company where id = #{id}")
    @org.apache.ibatis.annotations.Options(timeout = 2)
    Company getById(Long id);

    void update(Company company);

    @Delete("delete from company where id = #{id}")
    void deleteById(Long id);

    @Select("select * from company where status = 1 order by id desc")
    List<Company> listAll();

    @Select("select * from company where name = #{name} limit 1")
    Company getByName(String name);
}
