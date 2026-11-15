package com.job.service.impl;

import com.job.context.BaseContext;
import com.job.dto.ResumeDTO;
import com.job.entity.Resume;
import com.job.mapper.ResumeMapper;
import com.job.service.ResumeService;
import com.job.utils.ResumeParseUtil;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Service
public class ResumeServiceImpl implements ResumeService {

    @Autowired
    private ResumeMapper resumeMapper;

    @Override
    public void save(ResumeDTO resumeDTO) {
        Resume resume = new Resume();
        BeanUtils.copyProperties(resumeDTO, resume);
        resume.setUserId(BaseContext.getCurrentId());
        resume.setCreateTime(LocalDateTime.now());
        resume.setUpdateTime(LocalDateTime.now());
        if (resume.getIsDefault() == null) {
            resume.setIsDefault(0);
        }
        if (resume.getIsDefault() == 1) {
            resumeMapper.clearDefault(resume.getUserId());
        }
        resumeMapper.insert(resume);
    }

    @Override
    public List<Resume> list() {
        return resumeMapper.listByUserId(BaseContext.getCurrentId());
    }

    @Override
    public Resume getById(Long id) {
        return resumeMapper.getById(id);
    }

    @Override
    public void update(ResumeDTO resumeDTO) {
        Resume resume = new Resume();
        BeanUtils.copyProperties(resumeDTO, resume);
        resume.setUpdateTime(LocalDateTime.now());
        resumeMapper.update(resume);
    }

    @Override
    public void deleteById(Long id) {
        resumeMapper.deleteById(id);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void setDefault(Long id) {
        Resume resume = resumeMapper.getById(id);
        Long userId = BaseContext.getCurrentId();
        resumeMapper.clearDefault(userId);
        Resume update = new Resume();
        update.setId(id);
        update.setIsDefault(1);
        update.setUpdateTime(LocalDateTime.now());
        resumeMapper.update(update);
    }

    @Override
    public Map<String, Object> parse(String text) {
        // 简历解析走本地规则解析，不依赖 AI Agent
        return ResumeParseUtil.parse(text);
    }
}
