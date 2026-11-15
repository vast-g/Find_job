package com.job.service;

import com.job.dto.ResumeDTO;
import com.job.entity.Resume;

import java.util.List;
import java.util.Map;

public interface ResumeService {

    void save(ResumeDTO resumeDTO);

    List<Resume> list();

    Resume getById(Long id);

    void update(ResumeDTO resumeDTO);

    void deleteById(Long id);

    void setDefault(Long id);

    Map<String, Object> parse(String text);
}
