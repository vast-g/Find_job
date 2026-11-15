package com.job.mapper;

import com.github.pagehelper.Page;
import com.job.dto.JobCategoryDTO;
import com.job.entity.JobCategory;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface JobCategoryMapper {

    void insert(JobCategory jobCategory);

    Page<JobCategory> pageQuery(JobCategoryDTO jobCategoryDTO);

    @Select("select * from job_category where id = #{id}")
    JobCategory getById(Long id);

    void update(JobCategory jobCategory);

    @Delete("delete from job_category where id = #{id}")
    void deleteById(Long id);

    @Select("select * from job_category where status = 1 order by sort asc, id desc")
    List<JobCategory> listEnabled();

    @Select("select * from job_category where name = #{name} limit 1")
    JobCategory getByName(String name);
}
