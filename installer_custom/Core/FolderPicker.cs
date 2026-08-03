using System;
using System.Runtime.InteropServices;

namespace XXAR.Setup
{
    // Vista-style folder browser through the shell's IFileOpenDialog.
    public static class FolderPicker
    {
        public static string Pick(IntPtr owner, string initialPath)
        {
            var dialog = (IFileOpenDialog)new FileOpenDialogCoClass();
            try
            {
                dialog.GetOptions(out uint options);
                dialog.SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);

                if (!string.IsNullOrEmpty(initialPath))
                {
                    try
                    {
                        var guid = typeof(IShellItem).GUID;
                        if (SHCreateItemFromParsingName(initialPath, IntPtr.Zero, ref guid, out IShellItem item) == 0 && item != null)
                            dialog.SetFolder(item);
                    }
                    catch
                    {
                        // A bad starting path just means the dialog opens at its default location.
                    }
                }

                // 0x800704C7 == HRESULT_FROM_WIN32(ERROR_CANCELLED): the user closed the dialog.
                int hr = dialog.Show(owner);
                if (hr != 0) return null;

                dialog.GetResult(out IShellItem result);
                result.GetDisplayName(SIGDN_FILESYSPATH, out string path);
                return path;
            }
            finally
            {
                Marshal.ReleaseComObject(dialog);
            }
        }

        private const uint FOS_PICKFOLDERS = 0x00000020;
        private const uint FOS_FORCEFILESYSTEM = 0x00000040;
        private const uint FOS_PATHMUSTEXIST = 0x00000800;
        private const uint SIGDN_FILESYSPATH = 0x80058000;

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHCreateItemFromParsingName(
            string path, IntPtr bindingContext, ref Guid riid, out IShellItem item);

        [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"), ClassInterface(ClassInterfaceType.None)]
        private class FileOpenDialogCoClass { }

        [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IFileOpenDialog
        {
            [PreserveSig] int Show(IntPtr parent);
            void SetFileTypes();          // unused slots kept to preserve the vtable layout
            void SetFileTypeIndex(uint index);
            void GetFileTypeIndex(out uint index);
            void Advise();
            void Unadvise();
            void SetOptions(uint options);
            void GetOptions(out uint options);
            void SetDefaultFolder(IShellItem folder);
            void SetFolder(IShellItem folder);
            void GetFolder(out IShellItem folder);
            void GetCurrentSelection(out IShellItem item);
            void SetFileName(string name);
            void GetFileName(out string name);
            void SetTitle(string title);
            void SetOkButtonLabel(string text);
            void SetFileNameLabel(string label);
            void GetResult(out IShellItem item);
            void AddPlace(IShellItem item, int alignment);
            void SetDefaultExtension(string extension);
            void Close(int hr);
            void SetClientGuid(ref Guid guid);
            void ClearClientData();
            void SetFilter(IntPtr filter);
            void GetResults(out IntPtr items);
            void GetSelectedItems(out IntPtr items);
        }

        [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellItem
        {
            void BindToHandler(IntPtr bindCtx, ref Guid bhid, ref Guid riid, out IntPtr ppv);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string name);
            void GetAttributes(uint mask, out uint attributes);
            void Compare(IShellItem other, uint hint, out int order);
        }
    }
}
