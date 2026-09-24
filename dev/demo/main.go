package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Println("这是 dev/demo/main.go")
	wd, _ := os.Getwd()
	fmt.Println("  当前目录 :", wd)
	fmt.Println("  MOSS_HOME:", os.Getenv("MOSS_HOME"))
	fmt.Println("  数据目录 :", os.Getenv("MOSS_PLUGIN_DATA_DIR"))
}
