p = "fs/susfs.c"
s = open(p, encoding="utf-8", errors="surrogateescape").read()
old1 = "void susfs_add_sus_path(void __user **user_info) {"
new1 = "void susfs_add_sus_path_loop(void __user **user_info);\n" + old1
if s.count(old1) != 1:
    print("::warning::fs/susfs.c: susfs_add_sus_path 签名不是预期形态，跳过")
else:
    s = s.replace(old1, new1, 1)
    old2 = ("\tif (copy_from_user(&info, (struct st_susfs_sus_path __user*)*user_info, sizeof(info))) {\n"
            "\t\tinfo.err = -EFAULT;\n"
            "\t\tgoto out_copy_to_user;\n"
            "\t}\n\n"
            "\tinfo.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);\n"
            "\tif (info.err) {\n"
            "\t\tSUSFS_LOGE(\"failed opening file '%s'\\n\", info.target_pathname);\n"
            "\t\tgoto out_copy_to_user;\n"
            "\t}\n")
    new2 = ("\tif (copy_from_user(&info, (struct st_susfs_sus_path __user*)*user_info, sizeof(info))) {\n"
            "\t\tinfo.err = -EFAULT;\n"
            "\t\tgoto out_copy_to_user;\n"
            "\t}\n\n"
            "\tinfo.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);\n"
            "\tif (info.err) {\n"
            "\t\tSUSFS_LOGE(\"failed opening '%s' in current ns, fallback to sus_path_loop\\n\", info.target_pathname);\n"
            "\t\t/* FINASU_SUS_PATH_LOOP_FALLBACK: 调用方命名空间解析不到（常见于 /storage/emulated 等 FUSE 路径）时，\n"
            "\t\t   退回 LOOP 机制，交由内核 workqueue 在 init 命名空间稍后解析并重新打标记 */\n"
            "\t\tsusfs_add_sus_path_loop(user_info);\n"
            "\t\treturn;\n"
            "\t}\n")
    if s.count(old2) != 1:
        print("::warning::fs/susfs.c: susfs_add_sus_path 代码形态不是预期，跳过回退")
    else:
        open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(old2, new2, 1))
        print("fs/susfs.c: 已加 SUSFS 路径隐藏 LOOP 回退")
