package com.job.controller.user;

import com.job.context.BaseContext;
import com.job.entity.User;
import com.job.mapper.UserMapper;
import com.job.result.Result;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestController("userMemberController")
@RequestMapping("/user/member")
@Api(tags = "C端会员接口")
public class MembershipController {

    @Autowired
    private UserMapper userMapper;

    @PostMapping("/open")
    @ApiOperation("开通会员")
    public Result open() {
        Long userId = BaseContext.getCurrentId();
        userMapper.openMember(userId, LocalDateTime.now().plusMonths(1));
        return Result.success();
    }

    @GetMapping("/status")
    @ApiOperation("会员状态")
    public Result<Map<String, Object>> status() {
        Long userId = BaseContext.getCurrentId();
        User user = userId == null ? null : userMapper.getById(userId);
        Map<String, Object> map = new HashMap<>();
        map.put("isMember", user != null && user.getIsMember() != null && user.getIsMember() == 1);
        map.put("memberExpireTime", user != null ? user.getMemberExpireTime() : null);
        return Result.success(map);
    }
}
