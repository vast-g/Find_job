package com.job.dto;

import lombok.Data;

import java.io.Serializable;
// 下面的 LRUCache / Solution 是遗留的算法练习题代码（与本 DTO 无关，全项目无引用），
// 原先缺少 java.util.Map / HashMap 的 import，导致 job-pojo 模块编译失败。
// 这里补 import 仅为让构建通过；建议后续直接删掉这两个类。
import java.util.HashMap;
import java.util.Map;

@Data
public class AgentAnalyzeDTO implements Serializable {

    private Long jobId;
}











