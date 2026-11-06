# FinaSU Kernel Builder

GKI_KernelSU_SUSFS 빌드 파이프라인에서 FinaSU 전용으로 추린 버전입니다.

## 변경점
- `finasu-src/kernel/` : 업로드한 FinaSU-master의 커널 소스 (빌드 시 이 소스가 사용됨, 수정 가능)
- `root-setup` 액션 : FinaSU일 때 `finasu-src/kernel`을 클론본 위에 덮어씀 (KSU 버전/태그 계산용으로만 upstream clone 유지)
- `main.yml` : Root Flavor는 FinaSU만 선택 가능. USB Arsenal/fanotify/pids/cfs_bw/abi_mode 입력 제거(항상 꺼짐/check)

## 기본 옵션 (스크린샷과 동일)
SUSFS, NoMount, Baseband Guard, Networking, DroidSpaces, NTSync, Ptrace Patch, Unicode Fix, BPF Stack = ON / Performance = OFF
브랜드 `Wild`, 페이지 4k, commit_mode `verified`.

## 사용법
1. 이 폴더 내용을 GitHub 저장소(main)에 푸시
2. Actions → Build Kernels → Run workflow (Kernel Version은 하나만 선택 권장, 예: 6.12.x-android16)
3. FinaSU는 SUSFS가 필수이므로 SUSFS를 끄지 말 것
