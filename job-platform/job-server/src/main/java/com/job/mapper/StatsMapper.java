package com.job.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface StatsMapper {

    @Select("select count(id) from company where status = 1")
    Integer countCompany();

    @Select("select count(id) from job where status = 1")
    Integer countJob();

    @Select("select count(id) from application where user_id = #{userId}")
    Integer countApply(Long userId);

    @Select("select count(id) from application where user_id = #{userId} and status in (1, 2, 3)")
    Integer countApplyProgress(Long userId);
}
