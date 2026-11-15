package com.job.mapper;

import com.job.entity.Resume;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

@Mapper
public interface ResumeMapper {

    void insert(Resume resume);

    @Select("select * from resume where user_id = #{userId} order by is_default desc, create_time desc")
    List<Resume> listByUserId(Long userId);

    @Select("select * from resume where id = #{id}")
    Resume getById(Long id);

    void update(Resume resume);

    @Delete("delete from resume where id = #{id}")
    void deleteById(Long id);

    @Update("update resume set is_default = 0 where user_id = #{userId}")
    void clearDefault(Long userId);

    @Select("select * from resume where user_id = #{userId} and is_default = 1 limit 1")
    Resume getDefault(Long userId);
}
