using System;
using System.IO;
using System.Diagnostics;
using System.Windows.Forms;
class MetroLauncher {
 [STAThread] static void Main() {
  try {
   string root=AppDomain.CurrentDomain.BaseDirectory;
   string python=Path.Combine(root,"runtime","python","pythonw.exe");
   string script=Path.Combine(root,"launch.py");
   if(!File.Exists(python)||!File.Exists(script)) throw new Exception("缺少运行文件，请把压缩包完整解压，保留 runtime 文件夹。");
   ProcessStartInfo p=new ProcessStartInfo(python,"-E -s \""+script+"\"");
   p.WorkingDirectory=root;p.UseShellExecute=false;p.CreateNoWindow=true;
   Process.Start(p);
  }catch(Exception e){MessageBox.Show(e.Message,"厦门地铁 · 启动提示",MessageBoxButtons.OK,MessageBoxIcon.Error);}
 }
}
