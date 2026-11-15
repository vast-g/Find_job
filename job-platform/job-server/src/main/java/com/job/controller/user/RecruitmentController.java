package com.job.controller.user;

import com.job.result.Result;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController("userRecruitmentController")
@RequestMapping("/user/recruitment")
@Api(tags = "C端校招进度接口")
public class RecruitmentController {

    private static final List<int[]> RANGES = new ArrayList<>();
    private static final List<String> NAMES = new ArrayList<>();
    private static final List<String> TIMES = new ArrayList<>();
    private static final List<String> DESCS = new ArrayList<>();

    static {
        RANGES.add(new int[]{7, 8});
        NAMES.add("提前批"); TIMES.add("7-8月");
        DESCS.add("提前批是央国企抢占优秀人才的先手，岗位少但竞争小、流程快，适合目标明确的同学提前锁定 offer。");

        RANGES.add(new int[]{9, 10, 11});
        NAMES.add("秋招黄金期"); TIMES.add("9-11月");
        DESCS.add("央国企最大规模的招聘季！90%以上的岗位在此阶段放出，覆盖所有专业和学历层次。宣讲会、双选会密集，从网申到笔试面试流程完整。每天刷新岗位列表，建立投递记录表，避免错过网申截止日期。多参加线下宣讲会，与HR建立联系。");

        RANGES.add(new int[]{12, 1});
        NAMES.add("秋招补录"); TIMES.add("12-1月");
        DESCS.add("秋招补录是错峰上岸的好机会，部分岗位未招满会重新开放，竞争相对缓和，适合秋招未拿到满意 offer 的同学。");

        RANGES.add(new int[]{2, 3, 4});
        NAMES.add("春季招聘"); TIMES.add("2-4月");
        DESCS.add("春季招聘是秋招后的第二次机会，岗位规模较秋招小，但仍有不少央国企补录，关注春招公告，及时投递。");

        RANGES.add(new int[]{5, 6});
        NAMES.add("春招补录"); TIMES.add("5-6月");
        DESCS.add("春招补录集中在毕业前最后阶段，岗位零散但上岸概率高，保持投递节奏，抓住最后窗口期。");
    }

    @GetMapping
    @ApiOperation("校招进度时间轴")
    public Result<Map<String, Object>> timeline() {
        int month = LocalDate.now().getMonthValue();
        List<Map<String, Object>> stages = new ArrayList<>();
        for (int i = 0; i < NAMES.size(); i++) {
            Map<String, Object> s = new HashMap<>();
            s.put("name", NAMES.get(i));
            s.put("time", TIMES.get(i));
            s.put("description", DESCS.get(i));
            stages.add(s);
        }
        Map<String, Object> result = new HashMap<>();
        result.put("currentIndex", currentIndex(month));
        result.put("stages", stages);
        return Result.success(result);
    }

    private int currentIndex(int month) {
        for (int i = 0; i < RANGES.size(); i++) {
            for (int m : RANGES.get(i)) {
                if (m == month) return i;
            }
        }
        return 1; // 默认秋招黄金期
    }
}
