import re as _re, sys as _sys

NEW_FS_EXTERNS = (
    "extern struct selinux_policy *backup_sepolicy;\n"
    "extern int security_context_to_sid_with_policy(struct selinux_policy *policy, const char *scontext, u32 scontext_len, u32 *sid, u32 def_sid, gfp_t gfp_flags, u32 *orig_sid_p, int *orig_rc_p);\n"
    "extern int security_sid_to_context_with_policy(struct selinux_policy *policy, u32 sid, char **scontext, u32 *scontext_len);\n"
    "extern void security_compute_av_user_with_policy(struct selinux_policy *policy, u32 ssid, u32 tsid, u16 tclass, struct av_decision *avd);\n"
)
NEW_HK_EXTERNS = (
    "extern struct selinux_policy *backup_sepolicy;\n"
    "extern int security_context_to_sid_with_policy(struct selinux_policy *policy, const char *scontext, u32 scontext_len, u32 *sid, u32 def_sid, gfp_t gfp_flags, u32 *orig_sid_p, int *orig_rc_p);\n"
)

def _sub(path, name, old, new):
    s = open(path, encoding="utf-8", errors="surrogateescape").read()
    n = s.count(old)
    if n != 1:
        print("::warning::%s: %s count=%d (expect 1)" % (path, name, n))
        return
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(old, new, 1))
    print("%s: %s OK" % (path, name))

fs = "security/selinux/selinuxfs.c"
_sub(fs, "extern", "extern struct selinux_state fake_state;\n", NEW_FS_EXTERNS)
_sub(fs, "ctx", "security_context_to_sid(&fake_state, buf, size, &sid, GFP_KERNEL)",
     "security_context_to_sid_with_policy(backup_sepolicy, buf, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL)")
_sub(fs, "sid2ctx", "security_sid_to_context(&fake_state, sid, &canon, &len)",
     "security_sid_to_context_with_policy(backup_sepolicy, sid, &canon, &len)")
_sub(fs, "scon", "security_context_str_to_sid(&fake_state, scon, &ssid, GFP_KERNEL)",
     "security_context_to_sid_with_policy(backup_sepolicy, scon, strlen(scon), &ssid, SECSID_NULL, GFP_KERNEL, NULL, NULL)")
_sub(fs, "tcon", "security_context_str_to_sid(&fake_state, tcon, &tsid, GFP_KERNEL)",
     "security_context_to_sid_with_policy(backup_sepolicy, tcon, strlen(tcon), &tsid, SECSID_NULL, GFP_KERNEL, NULL, NULL)")
_sub(fs, "av", "security_compute_av_user(&fake_state, ssid, tsid, tclass, &avd)",
     "security_compute_av_user_with_policy(backup_sepolicy, ssid, tsid, tclass, &avd)")

hk = "security/selinux/hooks.c"
_sub(hk, "extern", "extern struct selinux_state fake_state;\n", NEW_HK_EXTERNS)

# <6.6 形态：resolve(&fake_state, value) -> _with_policy(8 参)
#   6.1 主补丁为多行 &sid；5.15 主补丁为单行 &tmp_sid。两种都归一化。
_hs = open(hk, encoding="utf-8", errors="surrogateescape").read()
_hs, _n = _re.subn(r"security_context_to_sid\(&fake_state, value, size,\s*\n\s*&sid, GFP_KERNEL\)",
                   "security_context_to_sid_with_policy(backup_sepolicy, value, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL)", _hs)
_hs, _n15 = _re.subn(r"security_context_to_sid\(&fake_state, value, size, &tmp_sid, GFP_KERNEL\)",
                     "security_context_to_sid_with_policy(backup_sepolicy, value, size, &tmp_sid, SECSID_NULL, GFP_KERNEL, NULL, NULL)", _hs)
print("%s: setprocattr.ctx <6.6=%d/%d" % (hk, _n, _n15))
open(hk, "w", encoding="utf-8", errors="surrogateescape").write(_hs)

# >=6.6 形态：把已有的 6 参 _with_policy 声明/调用补成 8 参（新模型签名）
#   6.6 主补丁在 security/selinux/{hooks,selinuxfs}.c 里自带 6 参 extern 声明，
#   只把调用补成 8 参会报 "too many arguments to function call, expected 6, have 8"。
#   因此 extern 声明必须与调用一起改成 8 参（新 FinaSU 的定义是 8 参）。
for _lab, _f in (("selinuxfs", fs), ("hooks", hk)):
    _s = open(_f, encoding="utf-8", errors="surrogateescape").read()
    # (?!, NULL, NULL) 保证幂等：<6.6 已由上文 _sub 切成 8 参的调用不再重复追加
    _s, _n2 = _re.subn(r"(security_context_to_sid_with_policy\(backup_sepolicy,[^;]*?, GFP_KERNEL)\)(?!, NULL, NULL)", r"\1, NULL, NULL)", _s)
    _s, _nd = _re.subn(r"(security_context_to_sid_with_policy\(struct selinux_policy \*policy, const char \*scontext, u32 scontext_len,\s*\n\s*u32 \*sid, u32 def_sid, gfp_t gfp_flags)\);", r"\1, u32 *orig_sid_p, int *orig_rc_p);", _s)
    open(_f, "w", encoding="utf-8", errors="surrogateescape").write(_s)
    print("%s: _with_policy 8-arg normalize=%d decl=%d" % (_lab, _n2, _nd))

_hs = open(hk, encoding="utf-8", errors="surrogateescape").read()
# 主补丁 setprocattr 两种形态：
#   旧形态（~2026-08 前的主补丁）：定义 my_setprocattr，内含无条件 SETCURRENT avc_has_perm
#     —— 需要 rm_early 移除 + seq 重排（df03912f）；
#   现行形态（2026-10 起的主补丁）：内联改 selinux_setprocattr，用 should_check_current +
#     fake_error 门控 —— 权限顺序天然满足 df03912f，且 fake 解析经上文 setprocattr.ctx
#     转换后已走 8 参 _with_policy（sidtab 同步内置），rm_early/seq 无目标代码。
if "should_check_current" in _hs and "fake_error = security_context_to_sid_with_policy(backup_sepolicy, value, size, &tmp_sid, SECSID_NULL, GFP_KERNEL, NULL, NULL)" in _hs:
    print("%s: 主补丁为现行门控形态（should_check_current+fake_error），rm_early_setcurrent/seq 不适用，侧信道语义已覆盖" % hk)
else:
    # 去掉无条件 SETCURRENT 检查（df03912f）：覆盖 <6.6(&selinux_state) 与 >=6.6(无 state) 两种形态
    _removed = False
    for _rm in ("\terror = avc_has_perm(&selinux_state,\n\t\t\t\t     mysid, mysid, SECCLASS_PROCESS,\n\t\t\t\t     PROCESS__SETCURRENT, NULL);\n\n\tif (error)\n\t\treturn error;\n\n",
                "\terror = avc_has_perm(mysid, mysid, SECCLASS_PROCESS,\n\t\t\t\t     PROCESS__SETCURRENT, NULL);\n\n\tif (error)\n\t\treturn error;\n\n"):
        if _hs.count(_rm) == 1:
            _hs = _hs.replace(_rm, "", 1)
            _removed = True
            print("%s: rm_early_setcurrent OK" % hk)
            break
    if not _removed:
        print("::warning::%s: rm_early_setcurrent not matched" % hk)
    # 仅在 backup 解析失败时才检查 SETCURRENT
    _seq_done = False
    for _old2, _new2, _lab in (
        ("\t\terror = security_context_to_sid_with_policy(backup_sepolicy, value, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL);\n\t\tif (error)\n\t\t\treturn error;\n",
         "\t\terror = security_context_to_sid_with_policy(backup_sepolicy, value, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL);\n\t\tif (error) {\n\t\t\tint perm_error = avc_has_perm(&selinux_state, mysid, mysid, SECCLASS_PROCESS, PROCESS__SETCURRENT, NULL);\n\t\t\treturn perm_error ?: error;\n\t\t}\n", "<6.6"),
        ("\t\terror = security_context_to_sid_with_policy(backup_sepolicy, str, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL);\n\t\tif (error)\n\t\t\treturn error;\n",
         "\t\terror = security_context_to_sid_with_policy(backup_sepolicy, str, size, &sid, SECSID_NULL, GFP_KERNEL, NULL, NULL);\n\t\tif (error) {\n\t\t\tint perm_error = avc_has_perm(mysid, mysid, SECCLASS_PROCESS, PROCESS__SETCURRENT, NULL);\n\t\t\treturn perm_error ?: error;\n\t\t}\n", ">=6.6")):
        if _hs.count(_old2) == 1:
            _hs = _hs.replace(_old2, _new2, 1)
            _seq_done = True
            print("%s: seq(%s) OK" % (hk, _lab))
            break
    if not _seq_done:
        print("::warning::%s: seq not matched" % hk)
open(hk, "w", encoding="utf-8", errors="surrogateescape").write(_hs)
for _f in (fs, hk):
    _s = open(_f, encoding="utf-8", errors="surrogateescape").read()
    if "fake_state" in _s:
        _sys.stderr.write("::error::%s 仍有 fake_state 残留\n" % _f)
        _sys.exit(1)
