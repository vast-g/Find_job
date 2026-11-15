package com.job.controller.user;

import com.job.context.BaseContext;
import com.job.mapper.StatsMapper;
import com.job.result.Result;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RestController("userStatsController")
@RequestMapping("/user/stats")
@Api(tags = "C端数据统计接口")
public class StatsController {

    @Autowired
    private StatsMapper statsMapper;

    @GetMapping
    @ApiOperation("首页/投递统计数据")
    public Result<Map<String, Object>> stats() {
        Long userId = BaseContext.getCurrentId();
        Map<String, Object> map = new HashMap<>();
        map.put("companyCount", statsMapper.countCompany());
        map.put("jobCount", statsMapper.countJob());
        map.put("announcementCount", 0);
        map.put("applyTotal", userId == null ? 0 : statsMapper.countApply(userId));
        map.put("applyProgress", userId == null ? 0 : statsMapper.countApplyProgress(userId));
        map.put("applyRemind", 0);
        return Result.success(map);
    }
}
