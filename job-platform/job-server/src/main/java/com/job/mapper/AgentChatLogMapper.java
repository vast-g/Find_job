package com.job.mapper;

import com.job.entity.AgentChatLog;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface AgentChatLogMapper {

    @Insert("insert into agent_chat_log (user_id, session_id, role, content, create_time) " +
            "values (#{userId}, #{sessionId}, #{role}, #{content}, #{createTime})")
    void insert(AgentChatLog agentChatLog);

    @Select("select * from agent_chat_log where user_id = #{userId} and session_id = #{sessionId} order by create_time asc")
    List<AgentChatLog> listBySession(@Param("userId") Long userId, @Param("sessionId") String sessionId);

    @Select("select * from agent_chat_log where user_id = #{userId} order by create_time desc limit 100")
    List<AgentChatLog> listRecent(Long userId);
}
