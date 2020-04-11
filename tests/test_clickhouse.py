from testflows.core import TestScenario, Name, When, Then, Given, And

from clickhouse import *
from kubectl import *
from helpers import require_zookeeper


@TestScenario
@Name("test_ch_001. Insert quorum")
def test_ch_001(self):
    require_zookeeper()
    
    create_and_check("configs/test-ch-001-insert-quorum.yaml", 
                     {"apply_templates": {"templates/tpl-clickhouse-19.11.yaml"},
                      "pod_count": 2,
                      "do_not_delete": 1})
    
    chi = "test-ch-001-insert-quorum"
    host0 = "chi-test-ch-001-insert-quorum-default-0-0"
    host1 = "chi-test-ch-001-insert-quorum-default-0-1"

    create_table = """
    create table t1 on cluster default (a Int8, d DateTime default toStartOfDay(today()+1))
    Engine = ReplicatedMergeTree('/clickhouse/tables/{table}', '{replica}')
    partition by d order by a 
    TTL d + interval 5 second
    SETTINGS merge_with_ttl_timeout=5""".replace('\r', '').replace('\n', '')

    create_mv_table2 = """
    create table t2 on cluster default (a Int8)
    Engine = ReplicatedMergeTree('/clickhouse/tables/{table}', '{replica}')
    partition by tuple() order by a""".replace('\r', '').replace('\n', '')

    create_mv_table3 = """
    create table t3 on cluster default (a Int8)
    Engine = ReplicatedMergeTree('/clickhouse/tables/{table}', '{replica}')
    partition by tuple() order by a""".replace('\r', '').replace('\n', '')

    create_mv2 = "create materialized view t_mv2 on cluster default to t2 as select a from t1"
    create_mv3 = "create materialized view t_mv3 on cluster default to t3 as select a from t1"


    with Given("Tables t1, t2, t3 and MVs t1->t2, t1-t3 are created"):
        clickhouse_query(chi, create_table)
        clickhouse_query(chi, create_mv_table2)
        clickhouse_query(chi, create_mv_table3)
        
        clickhouse_query(chi, create_mv2)
        clickhouse_query(chi, create_mv3)
        
        clickhouse_query(chi, "insert into t1(a) values(1)")
        
        with When("Stop fetches for t2 at replica1"):
            clickhouse_query(chi, "system stop fetches default.t2", host=host1)
        
            with Then("Insert should fail since it can not reach the quorum"): 
                out = clickhouse_query_with_error(chi, "insert into t1(a) values(2)",  host=host0)
                assert "Timeout while waiting for quorum" in out
        
        # kubectl(f"exec {host0}-0 -n test -- cp /var/lib//clickhouse/data/default/t2/all_1_1_0/a.mrk2 /var/lib//clickhouse/data/default/t2/all_1_1_0/a.bin")
        # with Then("Corrupt data part in t2"):
        #    kubectl(f"exec {host0}-0 -n test -- sed -i \"s/b/c/\" /var/lib/clickhouse/data/default/t2/all_1_1_0/a.bin")
        
        with When("Resume fetches for t2 at replica1"):
            clickhouse_query(chi, "system start fetches default.t2", host=host1)
            time.sleep(5)

            with Then("Inserts should fail with an error regarding not satisfied quorum"):
                out = clickhouse_query_with_error(chi, "insert into t1(a) values(3)",  host=host0)
                assert "Quorum for previous write has not been satisfied yet" in out
                
            with And("Second insert of the same block should pass"):
                clickhouse_query(chi, "insert into t1(a) values(3)", host=host0)
                
            with And("Insert of the new block should fail"):
                out = clickhouse_query_with_error(chi, "insert into t1(a) values(4)",  host=host0)
                assert "Quorum for previous write has not been satisfied yet" in out
                
            with And("Second insert of the same block with 'deduplicate_blocks_in_dependent_materialized_views' setting should fail"):
                out = clickhouse_query_with_error(chi, "set deduplicate_blocks_in_dependent_materialized_views=1; insert into t1(a) values(5)",  host=host0)
                assert "Quorum for previous write has not been satisfied yet" in out
            
        out = clickhouse_query_with_error(chi, "select t1.a t1_a, t2.a t2_a from t1 left outer join t2 using (a) order by t1_a settings join_use_nulls=1")
        print(out)
        
        with When("Stop fetches for t1 at replica1"):
            clickhouse_query(chi, "system stop fetches default.t1", host=host1)
            
            with Then("Insert should fail since it can not reach the quorum"): 
                out = clickhouse_query_with_error(chi, "insert into t1(a,d) values(6, now())",  host=host0)
                assert "Timeout while waiting for quorum" in out

            ttl_tries = 3
            for i in range(ttl_tries):
                replica_pause = 10 * (i + 1)
                with Then(f"Wait {replica_pause} seconds and the data should be dropped by TTL, try={i}"):
                    time.sleep(replica_pause)
                    out = clickhouse_query(chi, "select count() from t1 where a=6", host=host0)
                    if out == "0":
                        break

            assert out == "0", error()
        
        with When("Resume fetches for t1 at replica1"):
            clickhouse_query(chi, "system start fetches default.t1", host=host1)

            replica_tries = 3

            for i in range(replica_tries):
                replica_pause = 10 * (i + 1)
                with Then(f"Wait {replica_pause} seconds and the data should replicated"):
                    time.sleep(replica_pause)
                    host1_delay = clickhouse_query(
                        chi,
                        "SELECT absolute_delay,queue_size FROM system.replicas WHERE database='default' AND table='t1'",
                        host=host1
                    )
                    host0_delay = clickhouse_query(
                        chi,
                        "SELECT absolute_delay,queue_size FROM system.replicas WHERE database='default' AND table='t1'",
                        host=host0
                    )
                    if host1_delay == "0\t0" and host0_delay == "0\t0":
                        break

                assert host1_delay == "0\t0" and host0_delay == "0\t0", error()

            with Then("Inserts should resume"):
                clickhouse_query(chi, "insert into t1(a) values(7)",  host=host0)

        # cat /var/log/clickhouse-server/clickhouse-server.log | grep t2 | grep -E "all_1_1_0|START|STOP"
