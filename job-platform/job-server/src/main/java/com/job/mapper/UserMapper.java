package com.job.mapper;

import com.job.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

@Mapper
public interface UserMapper {

    @Select("select * from user where openid = #{openid}")
    User getByOpenid(String openid);

    @Select("select * from user where id = #{id}")
    User getById(Long id);

    void insert(User user);

    @Update("update user set is_member = 1, member_expire_time = #{expireTime} where id = #{id}")
    void openMember(@Param("id") Long id, @Param("expireTime") LocalDateTime expireTime);
}
