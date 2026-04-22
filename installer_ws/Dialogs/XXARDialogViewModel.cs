using System;
using System.ComponentModel;
using System.Drawing;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Windows.Interop;
using WixSharp;
using WixSharp.UI.Forms;

namespace XXAR.Installer.Dialogs
{
    /// <summary>
    /// Shared navigation view-model for every XXAR-branded WPF dialog.
    /// Exposes Host (ManagedForm), the WiX shell, and the three nav methods
    /// the XAML buttons bind their Click handlers to.
    /// </summary>
    public class XXARDialogViewModel : INotifyPropertyChanged
    {
        public ManagedForm Host { get; set; }
        public ISession Session => Host?.Runtime?.Session;
        public IManagedUIShell Shell => Host?.Shell;

        public void GoPrev() => Shell?.GoPrev();
        public void GoNext() => Shell?.GoNext();
        public void Cancel() => Shell?.Cancel();

        public event PropertyChangedEventHandler PropertyChanged;
        protected void OnChanged([CallerMemberName] string name = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    /// <summary>
    /// Paints every surface that would otherwise flash light-colored
    /// during dialog Next/Back transitions. Covers three independent
    /// paint layers that each need their own fix:
    ///   - WinForms ManagedForm.BackColor (via ApplyDarkHost)
    ///   - WPF HwndSource.CompositionTarget.BackgroundColor (via
    ///     RegisterDarkWpfCompositionTarget → OnSourceChanged)
    ///   - The HwndSource's native HWND WM_ERASEBKGND, which bypasses
    ///     both of the above because WPF uses DirectComposition (via
    ///     HwndSource.AddHook → HwndSourceHook GDI FillRect)
    /// Every path uses XXARBgTopColor (#10123A) so the one-frame pre-
    /// render fill seamlessly meets WPF's actual gradient render.
    /// </summary>
    internal static class XXARHostStyling
    {
        private static readonly Color DarkHostColor = Color.FromArgb(0x10, 0x12, 0x3A);
        private static readonly System.Windows.Media.Color DarkWpfColor =
            System.Windows.Media.Color.FromArgb(0xFF, 0x10, 0x12, 0x3A);
        // COLORREF = 0x00BBGGRR
        private const uint HookBrushColorRef = 0x003A1210u;

        private static readonly IntPtr _darkBrush = CreateSolidBrush(HookBrushColorRef);

        public static void ApplyDarkHost(ManagedForm host)
        {
            if (host == null) return;
            host.BackColor = DarkHostColor;
            Recolor(host.Controls);
            for (var p = host.Parent; p != null; p = p.Parent)
                p.BackColor = DarkHostColor;
        }

        public static void RegisterDarkWpfCompositionTarget(System.Windows.Controls.UserControl dialog)
        {
            if (dialog == null) return;
            System.Windows.PresentationSource.AddSourceChangedHandler(dialog, OnSourceChanged);
        }

        private static void OnSourceChanged(object sender, System.Windows.SourceChangedEventArgs e)
        {
            if (!(e.NewSource is HwndSource src)) return;
            if (src.CompositionTarget != null)
                src.CompositionTarget.BackgroundColor = DarkWpfColor;
            src.AddHook(HwndSourceHook);
            // Force a repaint so the first WM_ERASEBKGND goes through our
            // hook — otherwise Windows may have already cleared the HWND
            // to its class brush (pure white) between HWND creation and
            // SourceChanged firing.
            if (src.Handle != IntPtr.Zero)
                InvalidateRect(src.Handle, IntPtr.Zero, true);
        }

        private static IntPtr HwndSourceHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            const int WM_ERASEBKGND = 0x0014;
            if (msg == WM_ERASEBKGND)
            {
                var rect = new RECT();
                GetClientRect(hwnd, ref rect);
                FillRect(wParam, ref rect, _darkBrush);
                handled = true;
                return (IntPtr)1;
            }
            return IntPtr.Zero;
        }

        private static void Recolor(System.Windows.Forms.Control.ControlCollection controls)
        {
            foreach (System.Windows.Forms.Control c in controls)
            {
                c.BackColor = DarkHostColor;
                if (c.HasChildren) Recolor(c.Controls);
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT { public int L, T, R, B; }

        [DllImport("gdi32.dll")] private static extern IntPtr CreateSolidBrush(uint colorref);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr hWnd, ref RECT r);
        [DllImport("user32.dll")] private static extern int FillRect(IntPtr hdc, ref RECT r, IntPtr hbr);
        [DllImport("user32.dll")] private static extern bool InvalidateRect(IntPtr hWnd, IntPtr lpRect, bool bErase);
    }
}
