package com.job.controller.user;

import com.job.dto.ResumeDTO;
import com.job.entity.Resume;
import com.job.result.Result;
import com.job.service.ResumeService;
import com.job.utils.ResumeParseUtil;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/user/resume")
@Api(tags = "C端简历接口")
@Slf4j
public class ResumeController {

    @Autowired
    private ResumeService resumeService;

    @GetMapping("/list")
    @ApiOperation("我的简历")
    public Result<List<Resume>> list() {
        return Result.success(resumeService.list());
    }

    @PostMapping
    @ApiOperation("新增简历")
    public Result save(@RequestBody ResumeDTO resumeDTO) {
        resumeService.save(resumeDTO);
        return Result.success();
    }

    @GetMapping("/{id}")
    @ApiOperation("简历详情")
    public Result<Resume> getById(@PathVariable Long id) {
        return Result.success(resumeService.getById(id));
    }

    @PutMapping
    @ApiOperation("修改简历")
    public Result update(@RequestBody ResumeDTO resumeDTO) {
        resumeService.update(resumeDTO);
        return Result.success();
    }

    @DeleteMapping("/{id}")
    @ApiOperation("删除简历")
    public Result deleteById(@PathVariable Long id) {
        resumeService.deleteById(id);
        return Result.success();
    }

    @PutMapping("/default/{id}")
    @ApiOperation("设为默认简历")
    public Result setDefault(@PathVariable Long id) {
        resumeService.setDefault(id);
        return Result.success();
    }

    @PostMapping("/parse")
    @ApiOperation("解析简历")
    public Result<Map<String, Object>> parse(@RequestBody Map<String, String> body) {
        return Result.success(resumeService.parse(body.get("text")));
    }

    @PostMapping("/parseFile")
    @ApiOperation("上传简历文件解析(Word/PDF)")
    public Result<Map<String, Object>> parseFile(@RequestParam("file") MultipartFile file) {
        try {
            String text = ResumeParseUtil.extractText(file);
            return Result.success(ResumeParseUtil.parse(text));
        } catch (Exception e) {
            return Result.error(e.getMessage());
        }
    }
}
