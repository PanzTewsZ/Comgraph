import bpy
import bmesh

obj = bpy.context.active_object

if obj is None or obj.type != 'MESH':
    print("กรุณาเลือกวัตถุชนิด Mesh")
else:
    # กลับสู่ OBJECT mode เพื่อให้เข้าถึง mesh data ได้ถูกต้อง
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = obj.data

    # ใช้ color attribute ที่ active อยู่ใน Blender
    color_attributes = getattr(mesh, "color_attributes", None)
    has_color = color_attributes is not None and len(color_attributes) > 0

    color_name = None
    color_domain = None
    color_data_type = None

    if has_color:
        color_attribute = getattr(color_attributes, "active_color", None)
        if color_attribute is None:
            color_attribute = color_attributes[0]

        color_name = color_attribute.name
        color_domain = color_attribute.domain
        color_data_type = color_attribute.data_type

    # สร้าง BMesh ชั่วคราว + triangulate
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.verts.index_update()
    bm.normal_update()

    # Normal ต้องใช้ inverse-transpose เมื่อวัตถุมี rotation หรือ scale
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()

    # ตรวจว่ามี UV layer ไหม
    if not bm.loops.layers.uv:
        bm.free()
        raise RuntimeError("ไม่พบ UV layer ในโมเดล — โปรดทำ UV Unwrap ก่อน (เช่น Smart UV Project)")

    uv_layer = bm.loops.layers.uv.active

    color_layer = None

    if has_color:
        # Blender เก็บสีได้ทั้งต่อ vertex (POINT) และต่อ face corner (CORNER)
        if color_domain == 'POINT':
            color_layers = bm.verts.layers
        elif color_domain == 'CORNER':
            color_layers = bm.loops.layers
        else:
            color_layers = None

        if color_layers is not None and color_data_type == 'FLOAT_COLOR':
            color_layer = color_layers.float_color.get(color_name)
        elif color_layers is not None and color_data_type == 'BYTE_COLOR':
            color_layer = color_layers.color.get(color_name)

        # ถ้า attribute อ่านไม่ได้ ให้ข้าม vertex color แต่ยัง export ข้อมูลอื่นต่อ
        if color_layer is None:
            print(f"⚠️ ข้าม Color Attribute '{color_name}' เพราะรูปแบบไม่รองรับ")
            has_color = False

    vertices = []
    uvs = []
    normals = []
    colors = []
    indices = []
    vertex_lookup = {}

    # เดินทุกหน้า (triangulated แล้ว จึงเป็นสามเหลี่ยม)
    for face in bm.faces:
        for loop in face.loops:
            v = loop.vert

            # world position
            world_coord = obj.matrix_world @ v.co
            position_values = (
                round(world_coord.x, 6),
                round(world_coord.z, 6),
                round(-world_coord.y, 6),
            )

            # ใช้ normal เดียวต่อ Blender vertex เพื่อไม่ให้ vertex แตกตามแต่ละหน้า
            local_normal = v.normal
            world_normal = (normal_matrix @ local_normal).normalized()
            normal_values = (
                float(round(world_normal.x, 6)),
                float(round(world_normal.z, 6)),
                float(round(-world_normal.y, 6)),
            )

            # ดึง UV จาก loop
            uv = loop[uv_layer].uv
            u = float(round(uv.x, 6))
            v_ = float(round(uv.y, 6))

            # NOTE:
            # โดยทั่วไป UV จาก Blender ใช้ตรงๆได้กับ three.js
            # ถ้าพบว่า texture กลับหัว ลองสลับเป็น: v_ = 1.0 - v_
            uv_values = (u, v_)

            color_values = ()
            if has_color:
                color_source = v if color_domain == 'POINT' else loop
                color = color_source[color_layer]
                color_values = (
                    float(round(color[0], 6)),
                    float(round(color[1], 6)),
                    float(round(color[2], 6)),
                )

            # ใช้ index ของ Blender vertex เท่านั้น จึง export position/normal เพียงชุดเดียว
            # ต่อ vertex ส่วน UV seam และ corner color จะใช้ค่าจาก loop แรกที่พบ
            vertex_key = v.index

            if vertex_key not in vertex_lookup:
                vertex_lookup[vertex_key] = len(vertices) // 3
                vertices.extend(position_values)
                uvs.extend(uv_values)
                normals.extend(normal_values)
                if has_color:
                    colors.extend(color_values)

            indices.append(vertex_lookup[vertex_key])

    bm.free()

    # แปลงเป็น JavaScript array strings
    js_vertices = ', '.join(map(str, vertices))
    js_uvs = ', '.join(map(str, uvs))
    js_normals = ', '.join(map(str, normals))
    js_indices = ', '.join(map(str, indices))

    js_output = (
        "/* Auto-exported from Blender */\n"
        "const vertices = [\n  " + js_vertices + "\n];\n\n"
        "const uvs = [\n  " + js_uvs + "\n];\n\n"
        "const normals = [\n  " + js_normals + "\n];\n\n"
        "const indices = [\n  " + js_indices + "\n];\n"
    )

    if has_color:
        js_colors = ', '.join(map(str, colors))
        js_output += "\nconst colors = [\n  " + js_colors + "\n];\n"

    # เขียนลง Text Editor ชื่อ ExportedJS
    text_name = "ExportedJS"
    if text_name not in bpy.data.texts:
        bpy.data.texts.new(text_name)
    bpy.data.texts[text_name].clear()
    bpy.data.texts[text_name].write(js_output)

    if has_color:
        print(
            f"✅ Exported indexed mesh: {len(vertices) // 3} vertices, "
            f"{len(indices) // 3} triangles + UV + normal + "
            f"vertex color '{color_name}' ไปที่ TextBlock: {text_name}"
        )
    else:
        print(
            f"✅ Exported indexed mesh: {len(vertices) // 3} vertices, "
            f"{len(indices) // 3} triangles + UV + normal "
            f"(ไม่มี vertex color) ไปที่ TextBlock: {text_name}"
        )
