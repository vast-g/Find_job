package com.job.service;

import com.job.dto.UserLoginDTO;
import com.job.entity.User;

public interface UserService {

    User wxLogin(UserLoginDTO userLoginDTO);
}
