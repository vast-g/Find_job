package com.job.mapper;

import com.github.pagehelper.Page;
import com.job.dto.ApplicationPageQueryDTO;
import com.job.entity.Application;
import com.job.vo.ApplicationVO;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ApplicationMapper {

    @Insert("insert into application (user_id, job_id, resume_id, status, create_time, update_time) " +
            "values (#{userId}, #{jobId}, #{resumeId}, #{status}, #{createTime}, #{updateTime})")
    void insert(Application application);

    @Select("select count(id) from application where user_id = #{userId} and job_id = #{jobId}")
    Integer count(@Param("userId") Long userId, @Param("jobId") Long jobId);

    Page<ApplicationVO> pageQuery(ApplicationPageQueryDTO applicationPageQueryDTO);

    List<ApplicationVO> listByUserId(Long userId);

    @Select("select * from application where id = #{id}")
    Application getById(Long id);

    void update(Application application);
}
