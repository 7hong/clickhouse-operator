// Copyright 2019 Altinity Ltd and/or its affiliates. All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package clickhouse

import (
	"context"
	sqlmodule "database/sql"
	"fmt"
	"github.com/golang/glog"
	_ "github.com/mailru/go-clickhouse"
	"time"
)

type CHConnection struct {
	params *CHConnectionParams
	conn   *sqlmodule.DB
}

func NewConnection(params *CHConnectionParams) *CHConnection {
	c := &CHConnection{
		params: params,
	}
	c.connect()
	return c
}

func (c *CHConnection) connect() {
	dsn := c.makeDSN()
	glog.V(1).Infof("Establishing connection: %s", dsn)
	dbConnection, err := sqlmodule.Open("clickhouse", dsn)
	if err != nil {
		glog.V(1).Infof("FAILED Open(%s) %v", dsn, err)
		return
	}

	// Ping should be deadlined
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(defaultTimeout))
	defer cancel()

	if err := dbConnection.PingContext(ctx); err != nil {
		glog.V(1).Infof("FAILED Ping(%s) %v", dsn, err)
		_ = dbConnection.Close()
		return
	}

	c.conn = dbConnection
}

func (c *CHConnection) ensureConnected() bool {
	if c.conn != nil {
		glog.V(1).Infof("Already connected: %s", c.makeDSN())
		return true
	}

	c.connect()

	return c.conn != nil
}

// makeDSN is a wrapper over param's
func (c *CHConnection) makeDSN() string {
	return c.params.makeDSN()
}

// Query runs given sql query
func (c *CHConnection) Query(sql string) (*sqlmodule.Rows, error) {
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(defaultTimeout))
	defer cancel()

	return c.QueryContext(ctx, sql)
}

func (c *CHConnection) QueryContext(ctx context.Context, sql string) (*sqlmodule.Rows, error) {
	if len(sql) == 0 {
		return nil, nil
	}

	if !c.ensureConnected() {
		s := fmt.Sprintf("FAILED connect(%s) for SQL: %s", c.makeDSN(), sql)
		glog.V(1).Info(s)
		return nil, fmt.Errorf(s)
	}

	rows, err := c.conn.QueryContext(ctx, sql)
	if err != nil {
		s := fmt.Sprintf("FAILED Query(%s) %v for SQL: %s", c.makeDSN(), err, sql)
		glog.V(1).Info(s)
		return nil, err
	}

	// glog.V(1).Infof("clickhouse.Query(%s):'%s'", c.Hostname, sql)

	return rows, nil
}

func (c *CHConnection) Exec(sql string) error {
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(defaultTimeout))
	defer cancel()

	return c.ExecContext(ctx, sql)
}

// Exec runs given sql query
func (c *CHConnection) ExecContext(ctx context.Context, sql string) error {
	if len(sql) == 0 {
		return nil
	}

	if !c.ensureConnected() {
		s := fmt.Sprintf("FAILED connect(%s) for SQL: %s", c.makeDSN(), sql)
		glog.V(1).Info(s)
		return fmt.Errorf(s)
	}

	_, err := c.conn.ExecContext(ctx, sql)

	if err != nil {
		glog.V(1).Infof("FAILED Exec(%s) %v for SQL: %s", c.makeDSN(), err, sql)
		return err
	}

	// glog.V(1).Infof("clickhouse.Exec(%s):'%s'", c.Hostname, sql)

	return nil
}
