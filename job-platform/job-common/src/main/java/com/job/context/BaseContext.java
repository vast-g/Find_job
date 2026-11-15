package com.job.context;

/** Request-scoped identity. Business IDs stay unchanged; Agent IDs include the role. */
public class BaseContext {

    public enum Role { ADMIN, USER }

    public static ThreadLocal<Long> threadLocal = new ThreadLocal<>();
    private static final ThreadLocal<Role> roleLocal = new ThreadLocal<>();

    public static void setCurrentId(Long id) {
        threadLocal.set(id);
    }

    public static void setCurrentIdentity(Long id, Role role) {
        if (id == null || id <= 0 || role == null) {
            throw new IllegalArgumentException("Invalid login identity");
        }
        threadLocal.set(id);
        roleLocal.set(role);
    }

    public static Long getCurrentId() {
        return threadLocal.get();
    }

    public static Role getCurrentRole() {
        return roleLocal.get();
    }

    /** Internal Agent namespace: candidate IDs are positive, administrator IDs negative.
     * Existing signed BIGINT stores need no migration. Never use a negative ID to query
     * candidate-owned business data. Legacy positive records remain candidate records.
     */
    public static Long getAgentId() {
        Long id = getCurrentId();
        if (id == null || id <= 0 || getCurrentRole() == null) {
            throw new IllegalStateException("Login required");
        }
        return getCurrentRole() == Role.ADMIN ? -id : id;
    }

    public static void removeCurrentId() {
        threadLocal.remove();
        roleLocal.remove();
    }
}
