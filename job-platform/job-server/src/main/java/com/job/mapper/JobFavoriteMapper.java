package com.job.mapper;

import com.job.entity.JobFavorite;
import com.job.vo.JobVO;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface JobFavoriteMapper {

    @Insert("insert into job_favorite (user_id, job_id, create_time) values (#{userId}, #{jobId}, #{createTime})")
    void insert(JobFavorite jobFavorite);

    @Delete("delete from job_favorite where user_id = #{userId} and job_id = #{jobId}")
    void delete(@Param("userId") Long userId, @Param("jobId") Long jobId);

    @Select("select count(id) from job_favorite where user_id = #{userId} and job_id = #{jobId}")
    Integer count(@Param("userId") Long userId, @Param("jobId") Long jobId);

    List<JobVO> listByUserId(Long userId);
}
