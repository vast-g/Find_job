package com.job.controller.admin;

import com.job.entity.Announcement;
import com.job.result.Result;
import com.job.service.AnnouncementService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController("adminAnnouncementController")
@RequestMapping("/admin/announcement")
@Api(tags = "公告管理接口")
public class AnnouncementController {

    @Autowired
    private AnnouncementService announcementService;

    @GetMapping("/list")
    @ApiOperation("公告列表")
    public Result<List<Announcement>> list() {
        return Result.success(announcementService.listAll());
    }

    @GetMapping("/{id}")
    @ApiOperation("公告详情")
    public Result<Announcement> getById(@PathVariable Long id) {
        return Result.success(announcementService.getById(id));
    }

    @PostMapping
    @ApiOperation("新增公告")
    public Result save(@RequestBody Announcement announcement) {
        announcementService.save(announcement);
        return Result.success();
    }

    @PutMapping
    @ApiOperation("修改公告")
    public Result update(@RequestBody Announcement announcement) {
        announcementService.update(announcement);
        return Result.success();
    }

    @DeleteMapping("/{id}")
    @ApiOperation("删除公告")
    public Result deleteById(@PathVariable Long id) {
        announcementService.deleteById(id);
        return Result.success();
    }
}
