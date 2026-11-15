package com.job.mapper;

import com.github.pagehelper.Page;
import com.job.annotation.AutoFill;
import com.job.dto.JobPageQueryDTO;
import com.job.entity.Job;
import com.job.enumeration.OperationType;
import com.job.vo.JobVO;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;
import java.util.List;

@Mapper
public interface JobMapper {

    @AutoFill(OperationType.INSERT)
    void insert(Job job);

    Page<JobVO> pageQuery(JobPageQueryDTO jobPageQueryDTO);

    @Select("select * from job where id = #{id}")
    @org.apache.ibatis.annotations.Options(timeout = 2)
    Job getById(Long id);

    @AutoFill(OperationType.UPDATE)
    void update(Job job);

    @Delete("delete from job where id = #{id}")
    void deleteById(Long id);

    List<JobVO> listByCondition(Job job);

    @Select("select count(id) from job where company_id = #{companyId}")
    Integer countByCompanyId(Long companyId);

    @Select("select count(id) from job where category_id = #{categoryId}")
    Integer countByCategoryId(Long categoryId);

    @Update("update job set apply_count = apply_count + 1 where id = #{id}")
    void incrementApplyCount(Long id);

    @Update("update job set status = 2 where status = 1 and deadline < #{now}")
    void updateStatusEnded(LocalDateTime now);

    @Select("select * from job where title = #{title} and company_id = #{companyId} limit 1")
    Job getByTitleAndCompanyId(String title, Long companyId);

    @Update("<script>update job <set>" +
            "<if test='description != null'>description = #{description},</if>" +
            "<if test='requirement != null'>requirement = #{requirement},</if>" +
            "<if test='sourceUrl != null'>source_url = #{sourceUrl},</if>" +
            "</set> where id = #{id}</script>")
    void refreshCrawlContent(@Param("id") Long id, @Param("description") String description,
                             @Param("requirement") String requirement, @Param("sourceUrl") String sourceUrl);
}
