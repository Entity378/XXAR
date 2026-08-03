using System;
using System.Runtime.InteropServices;

namespace XXAR.Setup
{
    // Vista-style folder browser through the shell's IFileOpenDialog.
    public static class FolderBrowser
    {
        private const uint PickFolders = 0x00000020;
        private const uint ForceFileSystem = 0x00000040;
        private const uint PathMustExist = 0x00000800;
        private const uint FileSystemDisplayName = 0x80058000;

        // Null when the user closes the dialog without choosing.
        public static string Browse(IntPtr owner, string startFolder)
        {
            var dialog = (IFileOpenDialog)new FileOpenDialogCoClass();
            try
            {
                uint options;
                dialog.GetOptions(out options);
                dialog.SetOptions(options | PickFolders | ForceFileSystem | PathMustExist);
                PointAt(dialog, startFolder);

                if (dialog.Show(owner) != 0) return null;

                IShellItem chosen;
                dialog.GetResult(out chosen);
                string path;
                chosen.GetDisplayName(FileSystemDisplayName, out path);
                return path;
            }
            finally
            {
                Marshal.ReleaseComObject(dialog);
            }
        }

        private static void PointAt(IFileOpenDialog dialog, string startFolder)
        {
            if (string.IsNullOrEmpty(startFolder)) return;
            try
            {
                var itemId = typeof(IShellItem).GUID;
                IShellItem folder;
                if (SHCreateItemFromParsingName(startFolder, IntPtr.Zero, ref itemId, out folder) == 0 && folder != null)
                    dialog.SetFolder(folder);
            }
            catch
            {
                // A bad starting path only means the dialog opens at its default location.
            }
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHCreateItemFromParsingName(
            string path, IntPtr bindingContext, ref Guid itemId, out IShellItem item);

        [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"), ClassInterface(ClassInterfaceType.None)]
        private class FileOpenDialogCoClass { }

        [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IFileOpenDialog
        {
            [PreserveSig] int Show(IntPtr parent);
            void SetFileTypes();          // unused slots kept so the vtable layout stays correct
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
            void Close(int result);
            void SetClientGuid(ref Guid clientId);
            void ClearClientData();
            void SetFilter(IntPtr filter);
            void GetResults(out IntPtr items);
            void GetSelectedItems(out IntPtr items);
        }

        [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellItem
        {
            void BindToHandler(IntPtr bindContext, ref Guid handlerId, ref Guid itemId, out IntPtr instance);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint kind, [MarshalAs(UnmanagedType.LPWStr)] out string name);
            void GetAttributes(uint mask, out uint attributes);
            void Compare(IShellItem other, uint hint, out int order);
        }
    }
}
