package com.job.constant;

/**
 * 投递状态（7 类）
 */
public class ApplicationStatusConstant {

    public static final Integer DRAFT = 0;          // 待投递
    public static final Integer APPLIED = 1;        // 已投递
    public static final Integer WRITTEN_TEST = 2;   // 笔试
    public static final Integer INTERVIEW = 3;      // 面试
    public static final Integer NO_PROGRESS = 4;    // 长期无进展
    public static final Integer OFFER = 5;          // Offer
    public static final Integer REJECTED = 6;       // 已拒绝
}
