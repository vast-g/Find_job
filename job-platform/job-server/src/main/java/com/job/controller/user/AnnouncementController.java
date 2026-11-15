package com.job.controller.user;

import com.job.entity.Announcement;
import com.job.result.Result;
import com.job.service.AnnouncementService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController("userAnnouncementController")
@RequestMapping("/user/announcement")
@Api(tags = "C端招聘公告接口")
public class AnnouncementController {

    @Autowired
    private AnnouncementService announcementService;

    @GetMapping("/list")
    @ApiOperation("公告列表")
    public Result<List<Announcement>> list() {
        return Result.success(announcementService.list());
    }

    @GetMapping("/{id}")
    @ApiOperation("公告详情")
    public Result<Announcement> getById(@PathVariable Long id) {
        return Result.success(announcementService.getById(id));
    }
}
