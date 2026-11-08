//! Cloud-placeholder policy. Opening a dehydrated OneDrive file can download
//! it. The decision below is a pure function of Windows file attributes so it
//! can be tested without an account. This build does not call CfHydratePlaceholder.

pub const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0000_0400;
pub const FILE_ATTRIBUTE_OFFLINE: u32 = 0x0000_1000;
pub const FILE_ATTRIBUTE_RECALL_ON_OPEN: u32 = 0x0004_0000;
pub const FILE_ATTRIBUTE_PINNED: u32 = 0x0008_0000;
pub const FILE_ATTRIBUTE_UNPINNED: u32 = 0x0010_0000;
pub const FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: u32 = 0x0040_0000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CloudProbe {
    pub attributes: u32,
    pub reparse_tag: Option<u32>,
}

pub fn should_skip_content(probe: &CloudProbe) -> Option<&'static str> {
    if probe.attributes & FILE_ATTRIBUTE_OFFLINE != 0 {
        return Some("文件带有离线/云占位属性，已跳过内容，不会自动下载");
    }
    if probe.attributes & FILE_ATTRIBUTE_RECALL_ON_OPEN != 0
        || probe.attributes & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS != 0
    {
        return Some("打开文件会触发云端召回，已跳过内容，不会自动下载");
    }
    if let Some(tag) = probe.reparse_tag {
        if is_cloud_reparse(tag)
            && probe.attributes & FILE_ATTRIBUTE_UNPINNED != 0
            && probe.attributes & FILE_ATTRIBUTE_PINNED == 0
            && probe.attributes & FILE_ATTRIBUTE_OFFLINE != 0
        {
            return Some("云重解析点且未固定在本地，已跳过内容");
        }
    }
    None
}

pub fn is_cloud_reparse(tag: u32) -> bool {
    // IO_REPARSE_TAG_CLOUD through IO_REPARSE_TAG_CLOUD_F.
    (0x9000_001A..=0x9000_F01A).contains(&tag) && (tag & 0x0000_FFFF) == 0x001A
}

pub fn is_link_reparse(tag: u32) -> bool {
    tag == 0xA000_000C || tag == 0xA000_0003
}

#[cfg(windows)]
pub fn probe_path(path: &std::path::Path) -> Option<CloudProbe> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::GetFileAttributesW;
    let wide = long_wide(path);
    let attrs = unsafe { GetFileAttributesW(PCWSTR(wide.as_ptr())) };
    if attrs == u32::MAX {
        return None;
    }
    Some(CloudProbe {
        attributes: attrs,
        reparse_tag: None,
    })
}

#[cfg(not(windows))]
pub fn probe_path(_path: &std::path::Path) -> Option<CloudProbe> {
    None
}

#[cfg(windows)]
fn long_wide(path: &std::path::Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    let text = path.as_os_str();
    let mut v: Vec<u16> = text.encode_wide().collect();
    v.push(0);
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recall_and_offline_are_skipped_without_a_live_account() {
        assert!(should_skip_content(&CloudProbe {
            attributes: FILE_ATTRIBUTE_OFFLINE,
            reparse_tag: Some(0x9000_001A),
        })
        .is_some());
        assert!(should_skip_content(&CloudProbe {
            attributes: FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
            reparse_tag: None,
        })
        .is_some());
        assert!(should_skip_content(&CloudProbe {
            attributes: FILE_ATTRIBUTE_RECALL_ON_OPEN,
            reparse_tag: None,
        })
        .is_some());
        assert!(should_skip_content(&CloudProbe {
            attributes: FILE_ATTRIBUTE_PINNED,
            reparse_tag: Some(0x9000_001A),
        })
        .is_none());
        assert!(should_skip_content(&CloudProbe {
            attributes: 0,
            reparse_tag: None,
        })
        .is_none());
    }
}
