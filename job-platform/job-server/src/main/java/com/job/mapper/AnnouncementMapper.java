package com.job.mapper;

import com.job.entity.Announcement;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

@Mapper
public interface AnnouncementMapper {

    @Select("select * from announcement where id = #{id}")
    Announcement getById(Long id);

    @Select("select * from announcement where status = 1 order by publish_time desc")
    List<Announcement> listEnabled();

    @Select("select * from announcement order by publish_time desc")
    List<Announcement> listAll();

    @Insert("insert into announcement (title, content, publish_time, status, create_time, update_time) " +
            "values (#{title}, #{content}, #{publishTime}, #{status}, #{createTime}, #{updateTime})")
    void insert(Announcement announcement);

    @Update("update announcement set title=#{title}, content=#{content}, publish_time=#{publishTime}, status=#{status}, update_time=#{updateTime} where id=#{id}")
    void update(Announcement announcement);

    @Delete("delete from announcement where id = #{id}")
    void deleteById(Long id);
}
