package com.job.service;

import com.job.entity.Announcement;

import java.util.List;

public interface AnnouncementService {

    List<Announcement> list();

    Announcement getById(Long id);

    void save(Announcement announcement);

    void update(Announcement announcement);

    void deleteById(Long id);

    List<Announcement> listAll();
}
