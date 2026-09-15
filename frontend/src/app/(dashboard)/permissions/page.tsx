"use client";

// ============================================================
// src/app/(dashboard)/permissions/page.tsx — 权限管理（用户/角色）
// shark Permissions/Index.vue → Next.js，完善权限管理功能
// ============================================================

import { useEffect, useState } from "react";
import {
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  listRoles,
  saveRole,
  listPermissions,
} from "@/lib/api/auth";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useAuthStore } from "@/stores/auth-store";

export default function PermissionsPage() {
  const isAdmin = useAuthStore((s) => s.isAdmin);
  const [users, setUsers] = useState<any[]>([]);
  const [roles, setRoles] = useState<any[]>([]);
  const [allPerms, setAllPerms] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // 新建用户表单
  const [newUser, setNewUser] = useState({ username: "", password: "", email: "", groups: [] as string[] });

  // 角色编辑
  const [editingRole, setEditingRole] = useState<{ id?: number; name: string; permissions: string[] } | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [u, r, p] = await Promise.all([listUsers(), listRoles(), listPermissions()]);
      setUsers(u);
      setRoles(r);
      setAllPerms(p);
    } catch (e) {
      toast.error("加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreateUser = async () => {
    if (!newUser.username || !newUser.password) return toast.error("用户名和密码必填");
    try {
      await createUser(newUser);
      toast.success("用户已创建");
      setNewUser({ username: "", password: "", email: "", groups: [] });
      load();
    } catch (e: any) {
      toast.error(e?.response?.data?.error || "创建失败");
    }
  };

  const handleToggleUserActive = async (u: any) => {
    await updateUser(u.id, { is_active: !u.is_active });
    load();
  };

  const handleDeleteUser = async (u: any) => {
    await deleteUser(u.id);
    toast.success("已删除");
    load();
  };

  const handleSaveRole = async () => {
    if (!editingRole?.name) return toast.error("角色名必填");
    await saveRole(editingRole);
    toast.success("角色已保存");
    setEditingRole(null);
    load();
  };

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">权限管理</h1>
        <p className="text-sm text-muted-foreground">用户、角色、细粒度权限管理</p>
      </div>

      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">用户 ({users.length})</TabsTrigger>
          <TabsTrigger value="roles">角色 ({roles.length})</TabsTrigger>
        </TabsList>

        {/* 用户 */}
        <TabsContent value="users" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>用户列表</CardTitle>
              <CardDescription>管理平台账号与角色分配</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>用户名</TableHead>
                    <TableHead>邮箱</TableHead>
                    <TableHead>角色</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.id}</TableCell>
                      <TableCell className="font-medium">{u.username}</TableCell>
                      <TableCell>{u.email || "-"}</TableCell>
                      <TableCell>
                        {(u.groups || []).map((g: string) => (
                          <Badge key={g} variant="secondary" className="mr-1">{g}</Badge>
                        ))}
                      </TableCell>
                      <TableCell>
                        <Badge variant={u.is_active ? "default" : "destructive"}>
                          {u.is_active ? "启用" : "禁用"}
                        </Badge>
                      </TableCell>
                      <TableCell className="space-x-2">
                        <Button size="sm" variant="outline" onClick={() => handleToggleUserActive(u)}>
                          {u.is_active ? "禁用" : "启用"}
                        </Button>
                        {u.username !== "admin" && (
                          <Button size="sm" variant="destructive" onClick={() => handleDeleteUser(u)}>删除</Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {isAdmin && (
                <div className="mt-4 flex items-end gap-3 rounded-lg border p-4">
                  <div className="space-y-1">
                    <Label>用户名</Label>
                    <Input value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} placeholder="username" />
                  </div>
                  <div className="space-y-1">
                    <Label>密码</Label>
                    <Input type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} placeholder="password" />
                  </div>
                  <div className="space-y-1">
                    <Label>邮箱</Label>
                    <Input value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} placeholder="optional" />
                  </div>
                  <Button onClick={handleCreateUser}>创建用户</Button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* 角色 */}
        <TabsContent value="roles" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>角色与权限</CardTitle>
              <CardDescription>为角色分配细粒度权限（codename）</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>角色</TableHead>
                    <TableHead>权限数</TableHead>
                    <TableHead>权限</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {roles.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell>{r.permissions?.length ?? 0}</TableCell>
                      <TableCell className="max-w-md">
                        <div className="flex flex-wrap gap-1">
                          {(r.permissions || []).slice(0, 6).map((p: string) => (
                            <Badge key={p} variant="outline">{p}</Badge>
                          ))}
                          {(r.permissions || []).length > 6 && <Badge variant="outline">+{r.permissions.length - 6}</Badge>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Button size="sm" variant="outline" onClick={() => setEditingRole({ id: r.id, name: r.name, permissions: r.permissions || [] })}>
                          编辑
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {isAdmin && (
                <div className="rounded-lg border p-4">
                  <Button variant="outline" onClick={() => setEditingRole({ name: "", permissions: [] })}>
                    + 新建角色
                  </Button>
                </div>
              )}

              {editingRole && (
                <Card className="border-primary/40">
                  <CardHeader>
                    <CardTitle>{editingRole.id ? "编辑角色" : "新建角色"}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-1">
                      <Label>角色名</Label>
                      <Input value={editingRole.name} onChange={(e) => setEditingRole({ ...editingRole, name: e.target.value })} />
                    </div>
                    <div>
                      <Label className="mb-2 block">权限</Label>
                      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                        {allPerms.map((p: any) => (
                          <label key={p.codename} className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={editingRole.permissions.includes(p.codename)}
                              onCheckedChange={(c) => {
                                const perms = c
                                  ? [...editingRole.permissions, p.codename]
                                  : editingRole.permissions.filter((x) => x !== p.codename);
                                setEditingRole({ ...editingRole, permissions: perms });
                              }}
                            />
                            <span title={p.codename}>{p.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="space-x-2">
                      <Button onClick={handleSaveRole}>保存</Button>
                      <Button variant="outline" onClick={() => setEditingRole(null)}>取消</Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
