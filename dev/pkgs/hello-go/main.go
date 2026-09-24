// hello-go —— 证明"加一种语言不用改宿主代码"。
//
// 它和 hello 包用的是**同一个包格式**（pkg.json + run 文件 + params + output），
// 区别只有 pkg.json 里一行 "runner": "go"，以及 system/runners.json 里
// go 那一条配置（ext / markers / interpreters / launch）。
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

func main() {
	// ---- 读参数（宿主注入的 JSON）----
	params := map[string]interface{}{}
	if raw := os.Getenv("MOSS_PKG_PARAMS"); raw != "" {
		_ = json.Unmarshal([]byte(raw), &params)
	}

	who := "世界"
	if v, ok := params["who"].(string); ok && v != "" {
		who = v
	}
	times := 1
	if v, ok := params["times"].(float64); ok && v > 0 {
		times = int(v)
	}
	if times > 100 {
		times = 100
	}

	// ---- 干活 ----
	greeting := fmt.Sprintf("你好，%s！（来自 Go）", who)
	for i := 0; i < times; i++ {
		fmt.Println(greeting)
	}

	// ---- 结构化返回 ----
	result := map[string]interface{}{
		"who": who, "times": times, "greeting": greeting, "lang": "go",
	}
	if rf := os.Getenv("MOSS_RESULT_FILE"); rf != "" {
		if b, err := json.Marshal(result); err == nil {
			_ = os.WriteFile(rf, b, 0644)
		}
	}

	fmt.Println()
	fmt.Println("参数来源 : MOSS_PKG_PARAMS =", strings.TrimSpace(os.Getenv("MOSS_PKG_PARAMS")))
	fmt.Println("数据目录 :", os.Getenv("MOSS_PLUGIN_DATA_DIR"))
	fmt.Println("安装根   :", os.Getenv("MOSS_HOME"))
}
