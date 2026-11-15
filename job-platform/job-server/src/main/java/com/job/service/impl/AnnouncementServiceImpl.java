package com.job.service.impl;

import com.job.entity.Announcement;
import com.job.mapper.AnnouncementMapper;
import com.job.service.AnnouncementService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class AnnouncementServiceImpl implements AnnouncementService {

    @Autowired
    private AnnouncementMapper announcementMapper;

    @Override
    @Cacheable(cacheNames = "announcement:list")
    public List<Announcement> list() {
        return announcementMapper.listEnabled();
    }

    @Override
    public Announcement getById(Long id) {
        return announcementMapper.getById(id);
    }

    @Override
    @CacheEvict(cacheNames = "announcement:list", allEntries = true)
    public void save(Announcement announcement) {
        announcement.setStatus(1);
        announcement.setCreateTime(LocalDateTime.now());
        announcement.setUpdateTime(LocalDateTime.now());
        if (announcement.getPublishTime() == null) {
            announcement.setPublishTime(LocalDateTime.now());
        }
        announcementMapper.insert(announcement);
    }

    @Override
    @CacheEvict(cacheNames = "announcement:list", allEntries = true)
    public void update(Announcement announcement) {
        announcement.setUpdateTime(LocalDateTime.now());
        announcementMapper.update(announcement);
    }

    @Override
    @CacheEvict(cacheNames = "announcement:list", allEntries = true)
    public void deleteById(Long id) {
        announcementMapper.deleteById(id);
    }

    @Override
    public List<Announcement> listAll() {
        return announcementMapper.listAll();
    }
}
