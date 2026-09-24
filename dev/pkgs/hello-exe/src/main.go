// hello-exe 的源码。它**不随出厂包分发** —— 出厂只带 build.cmd 产出的 main.exe。
//
// 包格式和 hello / hello-go 完全一样，区别只有 pkg.json 里
// "runner": "exe" 以及 entry 指向 main.exe。
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

func main() {
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

	greeting := fmt.Sprintf("你好，%s！（来自编译好的 Go exe）", who)
	for i := 0; i < times; i++ {
		fmt.Println(greeting)
	}

	result := map[string]interface{}{
		"who": who, "times": times, "greeting": greeting, "lang": "go", "compiled": true,
	}
	if rf := os.Getenv("MOSS_RESULT_FILE"); rf != "" {
		if b, err := json.Marshal(result); err == nil {
			_ = os.WriteFile(rf, b, 0644)
		}
	}

	fmt.Println()
	fmt.Println("参数来源 : MOSS_PKG_PARAMS =", strings.TrimSpace(os.Getenv("MOSS_PKG_PARAMS")))
	fmt.Println("运行方式 : 编译好的 exe（不需要 Go 工具链）")
}
